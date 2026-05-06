"""Unit tests for ChannelFlowTool — single tool, atomic state + render."""

from typing import Any

import pytest

from ark_agentic.agents.insurance.tools.channel_flow import ChannelFlowTool
from ark_agentic.core.types import (
    ToolCall,
    ToolLoopAction,
    ToolResultType,
    UIComponentToolEvent,
)


def _plan_ctx() -> dict[str, Any]:
    """三渠道分配：bonus 3000, survival_fund 3000, policy_loan 4000。"""
    return {
        "_plan_allocations": [
            {
                "title": "组合方案",
                "channels": ["bonus", "survival_fund", "policy_loan"],
                "allocations": [
                    {"channel": "bonus", "policy_no": "POL002", "amount": 3000},
                    {"channel": "survival_fund", "policy_no": "POL002", "amount": 3000},
                    {"channel": "policy_loan", "policy_no": "POL001", "amount": 4000},
                ],
            }
        ],
    }


def _tc(channel: str, action: str) -> ToolCall:
    return ToolCall(
        id=f"tc_{channel}_{action}",
        name="channel_flow",
        arguments={"channel": channel, "action": action},
    )


def _flows(result) -> dict[str, Any]:
    return result.metadata["state_delta"]["_channel_flows"]


def _commit(ctx: dict[str, Any], result) -> dict[str, Any]:
    delta = result.metadata.get("state_delta", {})
    ctx.update(delta)
    return ctx


@pytest.fixture
def tool() -> ChannelFlowTool:
    return ChannelFlowTool()


# ---- start ----


class TestStart:
    @pytest.mark.asyncio
    async def test_new_flow_seeds_from_allocations_and_renders(self, tool):
        """start 同时完成 state seed + 卡片渲染（A2UI 事件）。"""
        ctx = _plan_ctx()
        result = await tool.execute(_tc("bonus", "start"), context=ctx)

        assert result.result_type == ToolResultType.A2UI
        assert result.loop_action == ToolLoopAction.CONTINUE
        assert any(isinstance(ev, UIComponentToolEvent) for ev in result.events)

        flows = _flows(result)
        bonus = flows["channel_flows"]["bonus"]
        assert flows["active_channel"] == "bonus"
        assert bonus["step"] == "policy"
        assert bonus["status"] == "active"
        assert bonus["policy_no"] == "POL002"
        assert bonus["amount"] == 3000.0

        # digest 必须包含 active_channel 单字段（让 LLM 能直接读出）
        assert "active_channel=bonus" in result.llm_digest
        assert "step=policy" in result.llm_digest
        assert "channel=bonus" in result.llm_digest

    @pytest.mark.asyncio
    async def test_chinese_alias_normalized(self, tool):
        """开源模型常把'红利'直接写进 channel——工具应接受并 normalize。"""
        ctx = _plan_ctx()
        result = await tool.execute(_tc("红利", "start"), context=ctx)

        flows = _flows(result)
        # 工具 normalize 后写入英文 ID
        assert "bonus" in flows["channel_flows"]
        assert flows["active_channel"] == "bonus"
        # digest 也用英文 ID
        assert "channel=bonus" in result.llm_digest

    @pytest.mark.asyncio
    async def test_chinese_alias_full_phrase(self, tool):
        ctx = _plan_ctx()
        result = await tool.execute(
            _tc("生存金领取", "start"), context=ctx,
        )
        assert _flows(result)["active_channel"] == "survival_fund"

    @pytest.mark.asyncio
    async def test_unknown_channel_rejected(self, tool):
        result = await tool.execute(_tc("退保", "start"), context=_plan_ctx())
        assert result.is_error
        assert "不支持的渠道" in result.content

    @pytest.mark.asyncio
    async def test_unknown_action_rejected(self, tool):
        result = await tool.execute(_tc("bonus", "boom"), context=_plan_ctx())
        assert result.is_error
        assert "未知 action" in result.content

    @pytest.mark.asyncio
    async def test_no_allocation_returns_error(self, tool):
        ctx = {"_plan_allocations": [{"allocations": []}]}
        result = await tool.execute(_tc("bonus", "start"), context=ctx)
        assert result.is_error
        assert "在当前方案中没有分配" in result.content

    @pytest.mark.asyncio
    async def test_starting_second_channel_pauses_first(self, tool):
        ctx = _plan_ctx()
        _commit(ctx, await tool.execute(_tc("bonus", "start"), context=ctx))
        result = await tool.execute(_tc("survival_fund", "start"), context=ctx)

        flows = _flows(result)
        assert flows["active_channel"] == "survival_fund"
        assert flows["channel_flows"]["bonus"]["status"] == "paused"
        assert flows["channel_flows"]["survival_fund"]["status"] == "active"
        assert "active_channel=survival_fund" in result.llm_digest

    @pytest.mark.asyncio
    async def test_start_resumes_existing_paused_flow(self, tool):
        ctx = _plan_ctx()
        _commit(ctx, await tool.execute(_tc("bonus", "start"), context=ctx))
        _commit(ctx, await tool.execute(_tc("bonus", "confirm_policy"), context=ctx))
        _commit(ctx, await tool.execute(_tc("bonus", "interrupt"), context=ctx))

        result = await tool.execute(_tc("bonus", "start"), context=ctx)
        flows = _flows(result)
        assert flows["channel_flows"]["bonus"]["step"] == "amount"
        assert flows["channel_flows"]["bonus"]["status"] == "active"
        assert "step=amount" in result.llm_digest
        assert "active_channel=bonus" in result.llm_digest

    @pytest.mark.asyncio
    async def test_start_on_submitted_channel_rejected(self, tool):
        ctx = _plan_ctx()
        ctx["_channel_flows"] = {
            "channel_flows": {
                "bonus": {
                    "step": "done", "policy_no": "P", "amount": 1,
                    "bank_card": "x", "status": "submitted",
                }
            },
            "active_channel": None,
        }
        result = await tool.execute(_tc("bonus", "start"), context=ctx)
        assert result.is_error
        assert "已提交" in result.content


# ---- confirm_* ----


class TestConfirm:
    @pytest.mark.asyncio
    async def test_confirm_policy_advances_and_renders(self, tool):
        ctx = _plan_ctx()
        _commit(ctx, await tool.execute(_tc("bonus", "start"), context=ctx))
        result = await tool.execute(_tc("bonus", "confirm_policy"), context=ctx)

        # 仍然出 A2UI 卡（新状态）
        assert result.result_type == ToolResultType.A2UI
        flows = _flows(result)
        assert flows["channel_flows"]["bonus"]["step"] == "amount"
        assert "step=amount" in result.llm_digest
        assert "active_channel=bonus" in result.llm_digest

    @pytest.mark.asyncio
    async def test_render_uses_freshly_mutated_state_not_ctx(self, tool):
        """关键：同轮内即使 ctx 还是旧的，工具内部 render 也用新 state。
        模拟 asyncio.gather 场景下 ctx 不会被同轮的前一个工具的 state_delta
        污染——本工具自己保证 state 与 render 原子一致。"""
        ctx = _plan_ctx()
        _commit(ctx, await tool.execute(_tc("bonus", "start"), context=ctx))

        # 这里 ctx 已是 step=policy，调 confirm_policy 后 result 必须显示 step=amount
        result = await tool.execute(_tc("bonus", "confirm_policy"), context=ctx)
        assert "step=amount" in result.llm_digest
        # 而 ctx 本身这一刻还未被 commit（runtime 后续才合并）—— 工具自己保证一致
        assert ctx["_channel_flows"]["channel_flows"]["bonus"]["step"] == "policy"

    @pytest.mark.asyncio
    async def test_confirm_amount_fills_bank_card(self, tool):
        ctx = _plan_ctx()
        _commit(ctx, await tool.execute(_tc("bonus", "start"), context=ctx))
        _commit(ctx, await tool.execute(_tc("bonus", "confirm_policy"), context=ctx))
        result = await tool.execute(_tc("bonus", "confirm_amount"), context=ctx)

        bonus = _flows(result)["channel_flows"]["bonus"]
        assert bonus["step"] == "bank_card"
        assert bonus["bank_card"]
        assert "step=bank_card" in result.llm_digest

    @pytest.mark.asyncio
    async def test_confirm_bank_no_card_continue_no_event(self, tool):
        """confirm_bank 是终态——不出卡，不 STOP，不发 events。"""
        ctx = _plan_ctx()
        for action in ("start", "confirm_policy", "confirm_amount"):
            _commit(ctx, await tool.execute(_tc("bonus", action), context=ctx))

        result = await tool.execute(_tc("bonus", "confirm_bank"), context=ctx)

        assert result.result_type == ToolResultType.JSON
        assert result.loop_action == ToolLoopAction.CONTINUE
        assert result.events == []
        delta = result.metadata["state_delta"]
        assert delta["_submitted_channels"] == ["bonus"]
        bonus = delta["_channel_flows"]["channel_flows"]["bonus"]
        assert bonus["step"] == "done"
        assert bonus["status"] == "submitted"
        assert "active_channel=none" in result.llm_digest
        assert "remaining=[]" in result.llm_digest
        assert "红利领取办理已完成" in result.content

    @pytest.mark.asyncio
    async def test_confirm_bank_digest_lists_remaining_paused(self, tool):
        ctx = _plan_ctx()
        _commit(ctx, await tool.execute(_tc("bonus", "start"), context=ctx))
        _commit(ctx, await tool.execute(_tc("bonus", "interrupt"), context=ctx))
        _commit(ctx, await tool.execute(_tc("survival_fund", "start"), context=ctx))
        _commit(ctx, await tool.execute(_tc("survival_fund", "interrupt"), context=ctx))
        _commit(ctx, await tool.execute(_tc("policy_loan", "start"), context=ctx))
        _commit(ctx, await tool.execute(_tc("policy_loan", "confirm_policy"), context=ctx))
        _commit(ctx, await tool.execute(_tc("policy_loan", "confirm_amount"), context=ctx))

        result = await tool.execute(_tc("policy_loan", "confirm_bank"), context=ctx)

        assert "channel=policy_loan" in result.llm_digest
        assert "bonus" in result.llm_digest
        assert "survival_fund" in result.llm_digest
        assert "红利领取" in result.content
        assert "生存金领取" in result.content

    @pytest.mark.asyncio
    async def test_wrong_step_action_rejected(self, tool):
        ctx = _plan_ctx()
        _commit(ctx, await tool.execute(_tc("bonus", "start"), context=ctx))
        result = await tool.execute(_tc("bonus", "confirm_amount"), context=ctx)
        assert result.is_error
        assert "step=policy" in result.content

    @pytest.mark.asyncio
    async def test_confirm_without_start_rejected(self, tool):
        result = await tool.execute(
            _tc("bonus", "confirm_policy"), context=_plan_ctx(),
        )
        assert result.is_error
        assert "流程未启动" in result.content

    @pytest.mark.asyncio
    async def test_submitted_channel_cannot_advance(self, tool):
        ctx = _plan_ctx()
        ctx["_channel_flows"] = {
            "channel_flows": {
                "bonus": {
                    "step": "done", "policy_no": "P", "amount": 1,
                    "bank_card": "x", "status": "submitted",
                }
            },
            "active_channel": None,
        }
        result = await tool.execute(_tc("bonus", "confirm_policy"), context=ctx)
        assert result.is_error
        assert "已提交" in result.content


# ---- interrupt + back ----


class TestInterrupt:
    @pytest.mark.asyncio
    async def test_interrupt_no_card_clears_active(self, tool):
        ctx = _plan_ctx()
        _commit(ctx, await tool.execute(_tc("bonus", "start"), context=ctx))
        result = await tool.execute(_tc("bonus", "interrupt"), context=ctx)

        # 中断不出卡
        assert result.result_type == ToolResultType.JSON
        assert result.events == []
        flows = _flows(result)
        assert flows["channel_flows"]["bonus"]["status"] == "paused"
        assert flows["active_channel"] is None
        assert "active_channel=none" in result.llm_digest

    @pytest.mark.asyncio
    async def test_interrupt_unknown_flow_rejected(self, tool):
        result = await tool.execute(_tc("bonus", "interrupt"), context=_plan_ctx())
        assert result.is_error
        assert "没有进行中" in result.content

    @pytest.mark.asyncio
    async def test_back_amount_to_policy_renders(self, tool):
        ctx = _plan_ctx()
        _commit(ctx, await tool.execute(_tc("bonus", "start"), context=ctx))
        _commit(ctx, await tool.execute(_tc("bonus", "confirm_policy"), context=ctx))

        result = await tool.execute(_tc("bonus", "back"), context=ctx)
        # back 同样出 A2UI 卡显示新状态
        assert result.result_type == ToolResultType.A2UI
        bonus = _flows(result)["channel_flows"]["bonus"]
        assert bonus["step"] == "policy"
        assert "step=policy" in result.llm_digest

    @pytest.mark.asyncio
    async def test_back_bank_card_to_amount_clears_bank_card(self, tool):
        ctx = _plan_ctx()
        for action in ("start", "confirm_policy", "confirm_amount"):
            _commit(ctx, await tool.execute(_tc("bonus", action), context=ctx))

        result = await tool.execute(_tc("bonus", "back"), context=ctx)
        bonus = _flows(result)["channel_flows"]["bonus"]
        assert bonus["step"] == "amount"
        assert bonus["bank_card"] is None

    @pytest.mark.asyncio
    async def test_back_at_policy_rejected(self, tool):
        ctx = _plan_ctx()
        _commit(ctx, await tool.execute(_tc("bonus", "start"), context=ctx))
        result = await tool.execute(_tc("bonus", "back"), context=ctx)
        assert result.is_error
        assert "无法后退" in result.content

    @pytest.mark.asyncio
    async def test_back_then_forward_refills_bank_card(self, tool):
        ctx = _plan_ctx()
        for action in ("start", "confirm_policy", "confirm_amount"):
            _commit(ctx, await tool.execute(_tc("bonus", action), context=ctx))
        _commit(ctx, await tool.execute(_tc("bonus", "back"), context=ctx))

        result = await tool.execute(_tc("bonus", "confirm_amount"), context=ctx)
        bonus = _flows(result)["channel_flows"]["bonus"]
        assert bonus["step"] == "bank_card"
        assert bonus["bank_card"] is not None

    @pytest.mark.asyncio
    async def test_interrupt_preserves_step_for_later_resume(self, tool):
        ctx = _plan_ctx()
        _commit(ctx, await tool.execute(_tc("bonus", "start"), context=ctx))
        _commit(ctx, await tool.execute(_tc("bonus", "confirm_policy"), context=ctx))
        _commit(ctx, await tool.execute(_tc("bonus", "confirm_amount"), context=ctx))
        _commit(ctx, await tool.execute(_tc("bonus", "interrupt"), context=ctx))

        _commit(ctx, await tool.execute(_tc("survival_fund", "start"), context=ctx))
        _commit(ctx, await tool.execute(_tc("survival_fund", "interrupt"), context=ctx))

        result = await tool.execute(_tc("bonus", "start"), context=ctx)
        flows = _flows(result)
        assert flows["channel_flows"]["bonus"]["step"] == "bank_card"
        assert flows["channel_flows"]["bonus"]["status"] == "active"
        assert flows["active_channel"] == "bonus"
