"""Unit tests for SubmitWithdrawalTool — state-only policies, single operation_type param."""

import pytest

from ark_agentic.agents.insurance.tools.submit_withdrawal import (
    SubmitWithdrawalTool,
    _resolve_policies_from_state,
)
from ark_agentic.core.types import (
    AgentToolResult,
    CustomToolEvent,
    ToolCall,
    ToolLoopAction,
    ToolResultType,
)


def _plan_ctx(
    allocations: list[dict],
) -> dict:
    return {
        "_plan_allocations": [
            {
                "title": "plan",
                "channels": [],
                "allocations": allocations,
            }
        ]
    }


class TestResolvePoliciesFromState:
    def test_matches_survival_fund_channel(self) -> None:
        ctx = _plan_ctx(
            [
                {
                    "channel": "survival_fund",
                    "policy_no": "P001",
                    "amount": 12000,
                }
            ]
        )
        out = _resolve_policies_from_state("shengcunjin", ctx)
        assert out == [{"policy_no": "P001", "amount": "12000"}]

    def test_returns_none_when_no_plan_has_channel(self) -> None:
        ctx = _plan_ctx(
            [{"channel": "bonus", "policy_no": "P1", "amount": 100}]
        )
        assert _resolve_policies_from_state("shengcunjin", ctx) is None

    def test_first_matching_plan_wins(self) -> None:
        ctx = {
            "_plan_allocations": [
                {
                    "allocations": [
                        {
                            "channel": "survival_fund",
                            "policy_no": "A",
                            "amount": 1,
                        }
                    ]
                },
                {
                    "allocations": [
                        {
                            "channel": "survival_fund",
                            "policy_no": "B",
                            "amount": 2,
                        }
                    ]
                },
            ]
        }
        out = _resolve_policies_from_state("shengcunjin", ctx)
        assert out == [{"policy_no": "A", "amount": "1"}]

    def test_multiple_rows_same_channel(self) -> None:
        ctx = _plan_ctx(
            [
                {"channel": "bonus", "policy_no": "P1", "amount": 10},
                {"channel": "bonus", "policy_no": "P2", "amount": 20},
            ]
        )
        out = _resolve_policies_from_state("bonus", ctx)
        assert out == [
            {"policy_no": "P1", "amount": "10"},
            {"policy_no": "P2", "amount": "20"},
        ]


class TestSubmitWithdrawalToolExecute:
    @pytest.fixture
    def tool(self) -> SubmitWithdrawalTool:
        return SubmitWithdrawalTool()

    def test_only_operation_type_parameter(self, tool: SubmitWithdrawalTool) -> None:
        assert len(tool.parameters) == 1
        assert tool.parameters[0].name == "operation_type"

    @pytest.mark.asyncio
    async def test_happy_path_emits_start_flow_and_stops(
        self, tool: SubmitWithdrawalTool
    ) -> None:
        tc = ToolCall(
            id="c1",
            name="submit_withdrawal",
            arguments={"operation_type": "loan"},
        )
        ctx = _plan_ctx(
            [{"channel": "policy_loan", "policy_no": "L1", "amount": 5000}]
        )
        result = await tool.execute(tc, context=ctx)
        assert isinstance(result, AgentToolResult)
        assert result.result_type == ToolResultType.JSON
        assert result.content == {"message": "已提交办理请求"}
        assert result.loop_action == ToolLoopAction.STOP
        assert len(result.events) == 1
        ev = result.events[0]
        assert isinstance(ev, CustomToolEvent)
        assert ev.custom_type == "start_flow"
        assert ev.payload["flow_type"] == "E027Flow"
        assert ev.payload["query_msg"] == "保单号-L1，金额-5000"

    @pytest.mark.asyncio
    async def test_unknown_operation_type_error(
        self, tool: SubmitWithdrawalTool
    ) -> None:
        tc = ToolCall(
            id="c2",
            name="submit_withdrawal",
            arguments={"operation_type": "not_a_real_op"},
        )
        result = await tool.execute(tc, context=_plan_ctx([]))
        assert result.result_type == ToolResultType.ERROR
        assert result.is_error is True
        assert "未知的操作类型" in str(result.content)

    @pytest.mark.asyncio
    async def test_missing_state_returns_error(self, tool: SubmitWithdrawalTool) -> None:
        tc = ToolCall(
            id="c3",
            name="submit_withdrawal",
            arguments={"operation_type": "shengcunjin"},
        )
        result = await tool.execute(tc, context={})
        assert result.result_type == ToolResultType.ERROR
        assert "未找到匹配的保单数据" in str(result.content)

    @pytest.mark.asyncio
    async def test_empty_context_uses_empty_dict(
        self, tool: SubmitWithdrawalTool
    ) -> None:
        tc = ToolCall(
            id="c4",
            name="submit_withdrawal",
            arguments={"operation_type": "bonus"},
        )
        result = await tool.execute(tc, context=None)
        assert result.is_error is True
