"""Unit tests for ChannelFlowStart/Advance/Resume tools."""

from typing import Any

import pytest

from ark_agentic.agents.insurance.tools.channel_flow import (
    ChannelFlowAdvanceTool,
    ChannelFlowResumeTool,
    ChannelFlowStartTool,
)
from ark_agentic.core.types import (
    CustomToolEvent,
    ToolCall,
    ToolLoopAction,
    ToolResultType,
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


def _tc(name: str, args: dict[str, Any]) -> ToolCall:
    return ToolCall(id=f"tc_{name}", name=name, arguments=args)


def _flows(result) -> dict[str, Any]:
    return result.metadata["state_delta"]["_channel_flows"]


def _commit(ctx: dict[str, Any], result) -> dict[str, Any]:
    """模拟 runtime 把 state_delta merge 回 ctx，用于跨工具串测。"""
    delta = result.metadata.get("state_delta", {})
    ctx.update(delta)
    return ctx


# ---------- ChannelFlowStartTool ----------


class TestChannelFlowStart:
    @pytest.mark.asyncio
    async def test_new_flow_seeds_from_allocations(self):
        tool = ChannelFlowStartTool()
        ctx = _plan_ctx()
        result = await tool.execute(_tc("start", {"channel": "bonus"}), context=ctx)

        assert result.result_type == ToolResultType.JSON
        flows = _flows(result)
        assert flows["active_channel"] == "bonus"
        bonus = flows["channel_flows"]["bonus"]
        assert bonus["step"] == "policy"
        assert bonus["status"] == "active"
        assert bonus["policy_no"] == "POL002"
        assert bonus["amount"] == 3000.0
        assert bonus["bank_card"] is None
        assert "[渠道流:启动 channel=bonus step=policy]" == result.llm_digest

    @pytest.mark.asyncio
    async def test_unknown_channel_rejected(self):
        tool = ChannelFlowStartTool()
        result = await tool.execute(
            _tc("start", {"channel": "surrender"}), context=_plan_ctx(),
        )
        assert result.is_error

    @pytest.mark.asyncio
    async def test_no_allocation_returns_error(self):
        tool = ChannelFlowStartTool()
        ctx = {"_plan_allocations": [{"allocations": []}]}
        result = await tool.execute(_tc("start", {"channel": "bonus"}), context=ctx)
        assert result.is_error
        assert "未在当前方案中找到" in result.content

    @pytest.mark.asyncio
    async def test_starting_second_channel_pauses_first(self):
        tool = ChannelFlowStartTool()
        ctx = _plan_ctx()
        first = await tool.execute(_tc("start", {"channel": "bonus"}), context=ctx)
        _commit(ctx, first)

        second = await tool.execute(
            _tc("start", {"channel": "survival_fund"}), context=ctx,
        )
        flows = _flows(second)
        assert flows["active_channel"] == "survival_fund"
        assert flows["channel_flows"]["bonus"]["status"] == "paused"
        assert flows["channel_flows"]["survival_fund"]["status"] == "active"

    @pytest.mark.asyncio
    async def test_resume_existing_paused_flow(self):
        """重新 start 已有的 paused 渠道 = 恢复，step 不变。"""
        advance = ChannelFlowAdvanceTool()
        start = ChannelFlowStartTool()
        ctx = _plan_ctx()

        # bonus 进到 amount step 后中断
        _commit(ctx, await start.execute(_tc("s", {"channel": "bonus"}), context=ctx))
        _commit(ctx, await advance.execute(
            _tc("a", {"channel": "bonus", "action": "confirm_policy"}), context=ctx,
        ))
        _commit(ctx, await advance.execute(
            _tc("a", {"channel": "bonus", "action": "interrupt"}), context=ctx,
        ))

        # 重新 start bonus → 应保留 step=amount
        result = await start.execute(_tc("s2", {"channel": "bonus"}), context=ctx)
        flows = _flows(result)
        assert flows["channel_flows"]["bonus"]["step"] == "amount"
        assert flows["channel_flows"]["bonus"]["status"] == "active"
        assert "[渠道流:恢复 channel=bonus step=amount]" == result.llm_digest

    @pytest.mark.asyncio
    async def test_starting_submitted_channel_rejected(self):
        start = ChannelFlowStartTool()
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
        result = await start.execute(_tc("s", {"channel": "bonus"}), context=ctx)
        assert result.is_error
        assert "已提交" in result.content


# ---------- ChannelFlowAdvanceTool ----------


class TestChannelFlowAdvance:
    @pytest.mark.asyncio
    async def test_confirm_policy_advances_to_amount(self):
        start, advance = ChannelFlowStartTool(), ChannelFlowAdvanceTool()
        ctx = _plan_ctx()
        _commit(ctx, await start.execute(_tc("s", {"channel": "bonus"}), context=ctx))

        result = await advance.execute(
            _tc("a", {"channel": "bonus", "action": "confirm_policy"}), context=ctx,
        )
        flows = _flows(result)
        assert flows["channel_flows"]["bonus"]["step"] == "amount"
        assert "[渠道流:推进 channel=bonus step=amount]" == result.llm_digest

    @pytest.mark.asyncio
    async def test_confirm_amount_fills_bank_card(self):
        start, advance = ChannelFlowStartTool(), ChannelFlowAdvanceTool()
        ctx = _plan_ctx()
        _commit(ctx, await start.execute(_tc("s", {"channel": "bonus"}), context=ctx))
        _commit(ctx, await advance.execute(
            _tc("a", {"channel": "bonus", "action": "confirm_policy"}), context=ctx,
        ))

        result = await advance.execute(
            _tc("a", {"channel": "bonus", "action": "confirm_amount"}), context=ctx,
        )
        bonus = _flows(result)["channel_flows"]["bonus"]
        assert bonus["step"] == "bank_card"
        assert bonus["bank_card"]
        assert bonus["bank_card"] != "—"

    @pytest.mark.asyncio
    async def test_confirm_bank_emits_start_flow_event_and_stops(self):
        start, advance = ChannelFlowStartTool(), ChannelFlowAdvanceTool()
        ctx = _plan_ctx()
        for action in ("seed", "confirm_policy", "confirm_amount"):
            if action == "seed":
                _commit(ctx, await start.execute(
                    _tc("s", {"channel": "bonus"}), context=ctx,
                ))
            else:
                _commit(ctx, await advance.execute(
                    _tc("a", {"channel": "bonus", "action": action}), context=ctx,
                ))

        result = await advance.execute(
            _tc("a", {"channel": "bonus", "action": "confirm_bank"}), context=ctx,
        )

        assert result.loop_action == ToolLoopAction.STOP
        assert len(result.events) == 1
        ev = result.events[0]
        assert isinstance(ev, CustomToolEvent)
        assert ev.custom_type == "start_flow"
        assert ev.payload["flow_type"] == "bonus-claim"
        assert ev.payload["query_msg"] == "保单号-POL002，金额-3000.00"

        delta = result.metadata["state_delta"]
        assert delta["_submitted_channels"] == ["bonus"]
        bonus = delta["_channel_flows"]["channel_flows"]["bonus"]
        assert bonus["step"] == "done"
        assert bonus["status"] == "submitted"

    @pytest.mark.asyncio
    async def test_confirm_bank_digest_lists_remaining_paused(self):
        start, advance = ChannelFlowStartTool(), ChannelFlowAdvanceTool()
        ctx = _plan_ctx()

        # 启 bonus → 中断；启 survival_fund → 中断；启 policy_loan 全程办完
        _commit(ctx, await start.execute(_tc("s", {"channel": "bonus"}), context=ctx))
        _commit(ctx, await advance.execute(
            _tc("a", {"channel": "bonus", "action": "interrupt"}), context=ctx,
        ))
        _commit(ctx, await start.execute(
            _tc("s", {"channel": "survival_fund"}), context=ctx,
        ))
        _commit(ctx, await advance.execute(
            _tc("a", {"channel": "survival_fund", "action": "interrupt"}), context=ctx,
        ))
        _commit(ctx, await start.execute(
            _tc("s", {"channel": "policy_loan"}), context=ctx,
        ))
        _commit(ctx, await advance.execute(
            _tc("a", {"channel": "policy_loan", "action": "confirm_policy"}), context=ctx,
        ))
        _commit(ctx, await advance.execute(
            _tc("a", {"channel": "policy_loan", "action": "confirm_amount"}), context=ctx,
        ))

        result = await advance.execute(
            _tc("a", {"channel": "policy_loan", "action": "confirm_bank"}), context=ctx,
        )
        # remaining 列出仍 paused 的渠道（顺序无要求，但应都在）
        assert "channel=policy_loan" in result.llm_digest
        assert "bonus" in result.llm_digest
        assert "survival_fund" in result.llm_digest
        assert "红利领取" in result.content
        assert "生存金领取" in result.content

    @pytest.mark.asyncio
    async def test_interrupt_marks_paused_and_clears_active(self):
        start, advance = ChannelFlowStartTool(), ChannelFlowAdvanceTool()
        ctx = _plan_ctx()
        _commit(ctx, await start.execute(_tc("s", {"channel": "bonus"}), context=ctx))

        result = await advance.execute(
            _tc("a", {"channel": "bonus", "action": "interrupt"}), context=ctx,
        )
        flows = _flows(result)
        assert flows["channel_flows"]["bonus"]["status"] == "paused"
        assert flows["active_channel"] is None
        assert "[渠道流:暂停 channel=bonus step=policy]" == result.llm_digest

    @pytest.mark.asyncio
    async def test_wrong_step_action_rejected(self):
        start, advance = ChannelFlowStartTool(), ChannelFlowAdvanceTool()
        ctx = _plan_ctx()
        _commit(ctx, await start.execute(_tc("s", {"channel": "bonus"}), context=ctx))

        # bonus 在 step=policy 时调 confirm_amount → 拒绝
        result = await advance.execute(
            _tc("a", {"channel": "bonus", "action": "confirm_amount"}), context=ctx,
        )
        assert result.is_error
        assert "step=policy" in result.content

    @pytest.mark.asyncio
    async def test_advance_without_start_rejected(self):
        advance = ChannelFlowAdvanceTool()
        result = await advance.execute(
            _tc("a", {"channel": "bonus", "action": "confirm_policy"}),
            context=_plan_ctx(),
        )
        assert result.is_error
        assert "未启动" in result.content

    @pytest.mark.asyncio
    async def test_submitted_channel_cannot_advance(self):
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
        result = await ChannelFlowAdvanceTool().execute(
            _tc("a", {"channel": "bonus", "action": "confirm_policy"}), context=ctx,
        )
        assert result.is_error
        assert "已提交" in result.content


# ---------- ChannelFlowResumeTool ----------


class TestChannelFlowResume:
    @pytest.mark.asyncio
    async def test_resume_keeps_step(self):
        start, advance, resume = (
            ChannelFlowStartTool(), ChannelFlowAdvanceTool(), ChannelFlowResumeTool(),
        )
        ctx = _plan_ctx()
        _commit(ctx, await start.execute(_tc("s", {"channel": "bonus"}), context=ctx))
        _commit(ctx, await advance.execute(
            _tc("a", {"channel": "bonus", "action": "confirm_policy"}), context=ctx,
        ))
        _commit(ctx, await advance.execute(
            _tc("a", {"channel": "bonus", "action": "interrupt"}), context=ctx,
        ))

        result = await resume.execute(_tc("r", {"channel": "bonus"}), context=ctx)
        flows = _flows(result)
        assert flows["active_channel"] == "bonus"
        assert flows["channel_flows"]["bonus"]["step"] == "amount"
        assert flows["channel_flows"]["bonus"]["status"] == "active"

    @pytest.mark.asyncio
    async def test_resume_pauses_previous_active(self):
        start, resume = ChannelFlowStartTool(), ChannelFlowResumeTool()
        ctx = _plan_ctx()
        _commit(ctx, await start.execute(_tc("s", {"channel": "bonus"}), context=ctx))
        _commit(ctx, await ChannelFlowAdvanceTool().execute(
            _tc("a", {"channel": "bonus", "action": "interrupt"}), context=ctx,
        ))
        _commit(ctx, await start.execute(
            _tc("s", {"channel": "survival_fund"}), context=ctx,
        ))

        result = await resume.execute(_tc("r", {"channel": "bonus"}), context=ctx)
        flows = _flows(result)
        assert flows["active_channel"] == "bonus"
        assert flows["channel_flows"]["survival_fund"]["status"] == "paused"
        assert flows["channel_flows"]["bonus"]["status"] == "active"

    @pytest.mark.asyncio
    async def test_resume_unknown_flow_rejected(self):
        result = await ChannelFlowResumeTool().execute(
            _tc("r", {"channel": "bonus"}), context=_plan_ctx(),
        )
        assert result.is_error

    @pytest.mark.asyncio
    async def test_resume_submitted_rejected(self):
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
        result = await ChannelFlowResumeTool().execute(
            _tc("r", {"channel": "bonus"}), context=ctx,
        )
        assert result.is_error
        assert "已提交" in result.content
