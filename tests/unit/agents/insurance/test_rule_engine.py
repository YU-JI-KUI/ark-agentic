"""Unit tests for RuleEngineTool amount handling (aligned with intake guard + tool behavior)."""

import pytest

from ark_agentic.agents.insurance.tools.rule_engine import RuleEngineTool
from ark_agentic.core.types import ToolCall, ToolResultType


class _DummyClient:
    async def call(self, **kwargs):
        return {"policyAssertList": []}


@pytest.mark.asyncio
class TestRuleEngineAmountValidation:
    async def test_list_options_negative_amount_returns_json(self) -> None:
        tool = RuleEngineTool(client=_DummyClient())
        tc = ToolCall(
            id="r1",
            name="rule_engine",
            arguments={
                "action": "list_options",
                "user_id": "U001",
                "amount": -10000,
            },
        )

        result = await tool.execute(tc, context={})

        assert result.result_type == ToolResultType.JSON
        assert result.content["requested_amount"] == -10000

    async def test_calculate_detail_negative_amount_returns_json(self) -> None:
        tool = RuleEngineTool(client=_DummyClient())
        tc = ToolCall(
            id="r2",
            name="rule_engine",
            arguments={
                "action": "calculate_detail",
                "policy": {
                    "policy_id": "P001",
                    "loan_amt": 50000,
                    "effective_date": "2020-01-01",
                },
                "option_type": "policy_loan",
                "amount": -1,
            },
        )

        result = await tool.execute(tc, context={})

        assert result.result_type == ToolResultType.JSON
        assert result.content["success"] is True
        assert result.content["actual_amount"] == -1

    async def test_zero_amount_list_options_returns_json(self) -> None:
        tool = RuleEngineTool(client=_DummyClient())
        tc = ToolCall(
            id="r3",
            name="rule_engine",
            arguments={
                "action": "list_options",
                "user_id": "U001",
                "amount": 0,
            },
        )

        result = await tool.execute(tc, context={})

        assert result.result_type == ToolResultType.JSON
        assert result.content["requested_amount"] == 0
