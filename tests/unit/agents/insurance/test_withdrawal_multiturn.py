"""Multi-turn integration tests for withdraw_money + execute_withdrawal skill chain.

Validates the complete state flow across turns:
  Turn 1: rule_engine -> render_a2ui(WithdrawPlanCard) -> llm_digest + _plan_allocations
  Turn 2: submit_withdrawal -> _submitted_channels updated, remaining shown
  Turn 3: submit_withdrawal (continuation) -> all done, no remaining
  Turn 4: new PlanCard (ADJUST) -> _submitted_channels reset to []

Uses real insurance tools (no LLM), simulating the tool call sequence
that the agent would produce across multiple conversation turns.
"""

import json

import pytest

from ark_agentic.agents.insurance.a2ui import INSURANCE_BLOCKS, INSURANCE_COMPONENTS
from ark_agentic.agents.insurance.tools.submit_withdrawal import SubmitWithdrawalTool
from ark_agentic.core.a2ui.theme import A2UITheme
from ark_agentic.core.tools.render_a2ui import BlocksConfig, RenderA2UITool
from ark_agentic.core.types import ToolCall, ToolLoopAction, ToolResultType


_SAMPLE_RAW_DATA = {
    "requested_amount": 50000,
    "total_available_incl_loan": 252800,
    "total_available_excl_loan": 219200,
    "options": [
        {
            "policy_id": "POL001",
            "product_name": "平安福终身寿险",
            "product_type": "whole_life",
            "policy_year": 8,
            "available_amount": 75600,
            "survival_fund_amt": 0,
            "bonus_amt": 0,
            "loan_amt": 33600,
            "refund_amt": 42000,
            "refund_fee_rate": 0.0,
        },
        {
            "policy_id": "POL002",
            "product_name": "金瑞人生年金险",
            "product_type": "annuity",
            "policy_year": 5,
            "available_amount": 177200,
            "survival_fund_amt": 12000,
            "bonus_amt": 5200,
            "loan_amt": 0,
            "refund_amt": 160000,
            "refund_fee_rate": 0.01,
        },
    ],
}


@pytest.fixture
def render_tool() -> RenderA2UITool:
    return RenderA2UITool(
        blocks=BlocksConfig(
            agent_blocks=INSURANCE_BLOCKS,
            agent_components=INSURANCE_COMPONENTS,
            theme=A2UITheme(root_gap=16, root_padding=[16, 32, 16, 16]),
        ),
        group="insurance",
        state_keys=("_rule_engine_result",),
    )


@pytest.fixture
def submit_tool() -> SubmitWithdrawalTool:
    return SubmitWithdrawalTool()


@pytest.fixture
def base_ctx() -> dict:
    return {
        "_rule_engine_result": _SAMPLE_RAW_DATA,
        "session_id": "test-multiturn",
    }


def _merge_state(ctx: dict, state_delta: dict) -> dict:
    """Simulate runner state merge: state_delta keys overwrite ctx."""
    merged = dict(ctx)
    for k, v in state_delta.items():
        merged[k] = v
    return merged


class TestMultiTurnWithdrawalFlow:
    """End-to-end multi-turn flow: PlanCard -> submit -> continuation -> ADJUST."""

    @pytest.mark.asyncio
    async def test_full_flow_plan_submit_continue_adjust(
        self, render_tool: RenderA2UITool, submit_tool: SubmitWithdrawalTool, base_ctx: dict,
    ) -> None:
        ctx = dict(base_ctx)

        # === Turn 1: render PlanCard (zero-cost: survival_fund + bonus) ===
        blocks = [
            {"type": "WithdrawPlanCard", "data": {
                "channels": ["survival_fund", "bonus"],
                "target": 0,
                "is_recommended": True,
            }},
        ]
        tc1 = ToolCall.create("render_a2ui", {"blocks": blocks})
        r1 = await render_tool.execute(tc1, context=ctx)

        assert not r1.is_error
        assert r1.llm_digest is not None
        assert r1.llm_digest.startswith("[卡片:方案")
        assert "survival_fund" in r1.llm_digest
        assert "bonus" in r1.llm_digest
        assert "total=" in r1.llm_digest

        delta1 = r1.metadata.get("state_delta", {})
        assert delta1["_submitted_channels"] == []
        assert len(delta1["_plan_allocations"]) == 1

        ctx = _merge_state(ctx, delta1)

        # === Turn 2: submit survival_fund ===
        tc2 = ToolCall(id="t2", name="submit_withdrawal", arguments={"operation_type": "shengcunjin"})
        r2 = await submit_tool.execute(tc2, context=ctx)

        assert not r2.is_error
        assert r2.loop_action == ToolLoopAction.STOP
        assert "生存金领取" in str(r2.content)
        assert "待办理" in str(r2.content), "bonus should still be pending"
        assert "红利领取" in str(r2.content)

        delta2 = r2.metadata.get("state_delta", {})
        assert "survival_fund" in delta2["_submitted_channels"]
        ctx = _merge_state(ctx, delta2)

        # === Turn 3: submit bonus (continuation) ===
        tc3 = ToolCall(id="t3", name="submit_withdrawal", arguments={"operation_type": "bonus"})
        r3 = await submit_tool.execute(tc3, context=ctx)

        assert not r3.is_error
        assert "待办理" not in str(r3.content), "All channels done"
        delta3 = r3.metadata.get("state_delta", {})
        assert set(delta3["_submitted_channels"]) == {"survival_fund", "bonus"}
        ctx = _merge_state(ctx, delta3)

        # === Turn 3.5: attempting to re-submit survival_fund is blocked ===
        tc3b = ToolCall(id="t3b", name="submit_withdrawal", arguments={"operation_type": "shengcunjin"})
        r3b = await submit_tool.execute(tc3b, context=ctx)
        assert "已提交办理" in str(r3b.content)

        # === Turn 4: ADJUST — new PlanCard resets _submitted_channels ===
        blocks_adjust = [
            {"type": "WithdrawPlanCard", "data": {
                "channels": ["policy_loan"],
                "target": 30000,
                "is_recommended": False,
            }},
        ]
        tc4 = ToolCall.create("render_a2ui", {"blocks": blocks_adjust})
        r4 = await render_tool.execute(tc4, context=ctx)

        assert not r4.is_error
        delta4 = r4.metadata.get("state_delta", {})
        assert delta4["_submitted_channels"] == [], (
            "ADJUST must reset _submitted_channels"
        )
        ctx = _merge_state(ctx, delta4)

        # === Turn 5: submit loan on new plan works ===
        tc5 = ToolCall(id="t5", name="submit_withdrawal", arguments={"operation_type": "loan"})
        r5 = await submit_tool.execute(tc5, context=ctx)
        assert not r5.is_error
        assert "保单贷款" in str(r5.content)


class TestDigestPropagationChain:
    """Verify llm_digest contains the correct format for downstream skill consumption."""

    @pytest.mark.asyncio
    async def test_digest_format_for_execute_skill_parsing(
        self, render_tool: RenderA2UITool, base_ctx: dict,
    ) -> None:
        """digest 必须以 `[卡片:方案 …]` 锚点开头，含 channels=[…] / total=…，供 execute_withdrawal 字段匹配。"""
        blocks = [
            {"type": "WithdrawPlanCard", "data": {
                "channels": ["survival_fund", "bonus"],
                "target": 50000,
                "is_recommended": True,
            }},
        ]
        tc = ToolCall.create("render_a2ui", {"blocks": blocks})
        result = await render_tool.execute(tc, context=base_ctx)

        digest = result.llm_digest
        assert digest is not None

        assert digest.startswith("[卡片:方案")
        assert "channels=[" in digest
        assert "total=" in digest

        assert "survival_fund" in digest
        assert "bonus" in digest
        assert "生存金" in digest
        assert "红利" in digest

    @pytest.mark.asyncio
    async def test_digest_does_not_leak_full_payload(
        self, render_tool: RenderA2UITool, base_ctx: dict,
    ) -> None:
        """Digest should be concise, not contain raw JSON or component IDs."""
        blocks = [
            {"type": "WithdrawPlanCard", "data": {
                "channels": ["survival_fund"],
                "target": 5000,
            }},
        ]
        tc = ToolCall.create("render_a2ui", {"blocks": blocks})
        result = await render_tool.execute(tc, context=base_ctx)

        digest = result.llm_digest
        assert "component" not in digest.lower()
        assert "Card" not in digest
        assert "explicitList" not in digest

    @pytest.mark.asyncio
    async def test_multiple_plan_cards_produce_separate_digests(
        self, render_tool: RenderA2UITool, base_ctx: dict,
    ) -> None:
        """Two PlanCards in one render_a2ui call produce two digest lines.

        现版本：title 由引擎从 actual_channels 派生，is_recommended=true 时带 ★ 推荐 前缀。
        """
        blocks = [
            {"type": "WithdrawPlanCard", "data": {
                "channels": ["survival_fund", "bonus"],
                "target": 10000,
                "is_recommended": True,
            }},
            {"type": "WithdrawPlanCard", "data": {
                "channels": ["policy_loan"],
                "target": 30000,
                "is_recommended": False,
            }},
        ]
        tc = ToolCall.create("render_a2ui", {"blocks": blocks})
        result = await render_tool.execute(tc, context=base_ctx)

        digest = result.llm_digest
        assert digest is not None
        # Plan A: target=10000 由 sf(12000) 单渠道吞掉 → 推荐: 生存金领取
        assert "★ 推荐" in digest
        assert "生存金" in digest
        # Plan B: 单渠道 policy_loan → 保单贷款（无 ★ 推荐 前缀）
        assert "保单贷款" in digest
        # 两条 digest 行（分隔符是换行符）
        assert digest.count("[卡片:方案") == 2


class TestStateInvariantsAcrossTurns:
    """Verify state invariants that prevent number hallucinations."""

    @pytest.mark.asyncio
    async def test_allocation_total_never_exceeds_available(
        self, render_tool: RenderA2UITool, base_ctx: dict,
    ) -> None:
        """Sum of allocations must not exceed what the channel actually has."""
        blocks = [
            {"type": "WithdrawPlanCard", "data": {
                "channels": ["survival_fund", "bonus"],
                "target": 999999,
            }},
        ]
        tc = ToolCall.create("render_a2ui", {"blocks": blocks})
        result = await render_tool.execute(tc, context=base_ctx)

        delta = result.metadata.get("state_delta", {})
        allocs = delta["_plan_allocations"][0]["allocations"]
        total_allocated = sum(a["amount"] for a in allocs)

        sf_available = 12000
        bonus_available = 5200
        assert total_allocated <= sf_available + bonus_available + 0.01, (
            f"Allocated {total_allocated} exceeds available {sf_available + bonus_available}"
        )

    @pytest.mark.asyncio
    async def test_submit_amount_matches_plan_allocation(
        self, render_tool: RenderA2UITool, submit_tool: SubmitWithdrawalTool, base_ctx: dict,
    ) -> None:
        """submit_withdrawal event payload amount must match what PlanCard allocated."""
        blocks = [
            {"type": "WithdrawPlanCard", "data": {
                "channels": ["survival_fund"],
                "target": 0,
                "is_recommended": True,
            }},
        ]
        tc1 = ToolCall.create("render_a2ui", {"blocks": blocks})
        r1 = await render_tool.execute(tc1, context=base_ctx)

        ctx = _merge_state(base_ctx, r1.metadata.get("state_delta", {}))

        plan_sf_amount = sum(
            a["amount"] for a in ctx["_plan_allocations"][0]["allocations"]
            if a["channel"] == "survival_fund"
        )

        tc2 = ToolCall(id="t2", name="submit_withdrawal", arguments={"operation_type": "shengcunjin"})
        r2 = await submit_tool.execute(tc2, context=ctx)

        ev = r2.events[0]
        query_msg = ev.payload["query_msg"]
        submitted_amount = float(query_msg.split("金额-")[1])
        assert submitted_amount == plan_sf_amount, (
            f"Submitted {submitted_amount} != planned {plan_sf_amount}"
        )
