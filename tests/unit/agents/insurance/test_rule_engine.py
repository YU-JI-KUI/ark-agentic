"""Unit tests for RuleEngineTool amount validation."""

from ark_agentic.agents.insurance.tools.rule_engine import RuleEngineTool
from ark_agentic.core.types import ToolCall, ToolResultType


class _DummyClient:
    async def call(self, **kwargs):
        return {"policyAssertList": []}


class TestRuleEngineAmountValidation:
    async def test_list_options_negative_amount_rejected(self) -> None:
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

        assert result.result_type == ToolResultType.ERROR
        assert "INVALID_AMOUNT_NON_POSITIVE" in str(result.content)
        assert "必须为正数" in str(result.content)

    async def test_calculate_detail_negative_amount_rejected(self) -> None:
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

        assert result.result_type == ToolResultType.ERROR
        assert "INVALID_AMOUNT_NON_POSITIVE" in str(result.content)

    async def test_zero_amount_rejected(self) -> None:
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

        assert result.result_type == ToolResultType.ERROR
        assert "INVALID_AMOUNT_NON_POSITIVE" in str(result.content)
