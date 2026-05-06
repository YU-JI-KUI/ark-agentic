"""Unit tests for ChannelFlowTool — single-tool state machine."""

from typing import Any

import pytest

from ark_agentic.agents.insurance.tools.channel_flow import ChannelFlowTool
from ark_agentic.core.types import ToolCall, ToolLoopAction, ToolResultType


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
    """模拟 runtime 把 state_delta merge 回 ctx。"""
    delta = result.metadata.get("state_delta", {})
    ctx.update(delta)
    return ctx


@pytest.fixture
def tool() -> ChannelFlowTool:
    return ChannelFlowTool()


# ---- start ----


class TestStart:
    @pytest.mark.asyncio
    async def test_new_flow_seeds_from_allocations(self, tool):
        ctx = _plan_ctx()
        result = await tool.execute(_tc("bonus", "start"), context=ctx)

        assert result.result_type == ToolResultType.JSON
        assert result.loop_action == ToolLoopAction.CONTINUE
        flows = _flows(result)
        bonus = flows["channel_flows"]["bonus"]
        assert flows["active_channel"] == "bonus"
        assert bonus["step"] == "policy"
        assert bonus["status"] == "active"
        assert bonus["policy_no"] == "POL002"
        assert bonus["amount"] == 3000.0
        assert bonus["bank_card"] is None
        assert result.llm_digest == "[渠道流:启动 channel=bonus step=policy]"

    @pytest.mark.asyncio
    async def test_unknown_channel_rejected(self, tool):
        result = await tool.execute(_tc("surrender", "start"), context=_plan_ctx())
        assert result.is_error

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
        assert "未在当前方案中找到" in result.content

    @pytest.mark.asyncio
    async def test_starting_second_channel_pauses_first(self, tool):
        ctx = _plan_ctx()
        _commit(ctx, await tool.execute(_tc("bonus", "start"), context=ctx))
        result = await tool.execute(_tc("survival_fund", "start"), context=ctx)

        flows = _flows(result)
        assert flows["active_channel"] == "survival_fund"
        assert flows["channel_flows"]["bonus"]["status"] == "paused"
        assert flows["channel_flows"]["survival_fund"]["status"] == "active"

    @pytest.mark.asyncio
    async def test_start_resumes_existing_paused_flow(self, tool):
        """对已存在的 paused 渠道再调 start = 恢复，step 不变。"""
        ctx = _plan_ctx()
        _commit(ctx, await tool.execute(_tc("bonus", "start"), context=ctx))
        _commit(ctx, await tool.execute(_tc("bonus", "confirm_policy"), context=ctx))
        _commit(ctx, await tool.execute(_tc("bonus", "interrupt"), context=ctx))

        result = await tool.execute(_tc("bonus", "start"), context=ctx)
        flows = _flows(result)
        assert flows["channel_flows"]["bonus"]["step"] == "amount"
        assert flows["channel_flows"]["bonus"]["status"] == "active"
        assert result.llm_digest == "[渠道流:恢复 channel=bonus step=amount]"

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
    async def test_confirm_policy_advances_to_amount(self, tool):
        ctx = _plan_ctx()
        _commit(ctx, await tool.execute(_tc("bonus", "start"), context=ctx))
        result = await tool.execute(_tc("bonus", "confirm_policy"), context=ctx)

        flows = _flows(result)
        assert flows["channel_flows"]["bonus"]["step"] == "amount"
        assert result.llm_digest == "[渠道流:推进 channel=bonus step=amount]"

    @pytest.mark.asyncio
    async def test_confirm_amount_fills_bank_card(self, tool):
        ctx = _plan_ctx()
        _commit(ctx, await tool.execute(_tc("bonus", "start"), context=ctx))
        _commit(ctx, await tool.execute(_tc("bonus", "confirm_policy"), context=ctx))
        result = await tool.execute(_tc("bonus", "confirm_amount"), context=ctx)

        bonus = _flows(result)["channel_flows"]["bonus"]
        assert bonus["step"] == "bank_card"
        assert bonus["bank_card"]
        assert bonus["bank_card"] != "—"

    @pytest.mark.asyncio
    async def test_confirm_bank_no_stop_no_event(self, tool):
        """confirm_bank 完成 status=submitted，但 NOT STOP，NOT events。"""
        ctx = _plan_ctx()
        for action in ("start", "confirm_policy", "confirm_amount"):
            _commit(ctx, await tool.execute(_tc("bonus", action), context=ctx))

        result = await tool.execute(_tc("bonus", "confirm_bank"), context=ctx)

        assert result.loop_action == ToolLoopAction.CONTINUE
        assert result.events == []
        delta = result.metadata["state_delta"]
        assert delta["_submitted_channels"] == ["bonus"]
        bonus = delta["_channel_flows"]["channel_flows"]["bonus"]
        assert bonus["step"] == "done"
        assert bonus["status"] == "submitted"
        assert delta["_channel_flows"]["active_channel"] is None
        assert result.llm_digest == "[渠道流:已提交 channel=bonus remaining=[]]"
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
        # bonus 在 step=policy 时调 confirm_amount → 拒绝
        result = await tool.execute(_tc("bonus", "confirm_amount"), context=ctx)
        assert result.is_error
        assert "step=policy" in result.content

    @pytest.mark.asyncio
    async def test_confirm_without_start_rejected(self, tool):
        result = await tool.execute(
            _tc("bonus", "confirm_policy"), context=_plan_ctx(),
        )
        assert result.is_error
        assert "未启动" in result.content

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


# ---- interrupt ----


class TestInterrupt:
    @pytest.mark.asyncio
    async def test_interrupt_marks_paused_and_clears_active(self, tool):
        ctx = _plan_ctx()
        _commit(ctx, await tool.execute(_tc("bonus", "start"), context=ctx))
        result = await tool.execute(_tc("bonus", "interrupt"), context=ctx)

        flows = _flows(result)
        assert flows["channel_flows"]["bonus"]["status"] == "paused"
        assert flows["active_channel"] is None
        assert result.llm_digest == "[渠道流:暂停 channel=bonus step=policy]"

    @pytest.mark.asyncio
    async def test_interrupt_unknown_flow_rejected(self, tool):
        result = await tool.execute(_tc("bonus", "interrupt"), context=_plan_ctx())
        assert result.is_error

    @pytest.mark.asyncio
    async def test_back_amount_to_policy(self, tool):
        ctx = _plan_ctx()
        _commit(ctx, await tool.execute(_tc("bonus", "start"), context=ctx))
        _commit(ctx, await tool.execute(_tc("bonus", "confirm_policy"), context=ctx))

        result = await tool.execute(_tc("bonus", "back"), context=ctx)
        bonus = _flows(result)["channel_flows"]["bonus"]
        assert bonus["step"] == "policy"
        assert result.llm_digest == "[渠道流:回退 channel=bonus step=policy]"

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
        """back 清掉 bank_card 后再 confirm_amount 必须重新填入。"""
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
        """中断后再 start = 接着上次 step 走。"""
        ctx = _plan_ctx()
        _commit(ctx, await tool.execute(_tc("bonus", "start"), context=ctx))
        _commit(ctx, await tool.execute(_tc("bonus", "confirm_policy"), context=ctx))
        _commit(ctx, await tool.execute(_tc("bonus", "confirm_amount"), context=ctx))
        _commit(ctx, await tool.execute(_tc("bonus", "interrupt"), context=ctx))

        # 期间办其他渠道
        _commit(ctx, await tool.execute(_tc("survival_fund", "start"), context=ctx))
        _commit(ctx, await tool.execute(_tc("survival_fund", "interrupt"), context=ctx))

        # 回到 bonus
        result = await tool.execute(_tc("bonus", "start"), context=ctx)
        flows = _flows(result)
        assert flows["channel_flows"]["bonus"]["step"] == "bank_card"
        assert flows["channel_flows"]["bonus"]["status"] == "active"
        assert flows["active_channel"] == "bonus"
