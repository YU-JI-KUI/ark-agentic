"""Tests for insurance a2ui extractors (withdraw_summary, withdraw_plan, policy_detail)."""

import json

import pytest

from ark_agentic.agents.insurance.a2ui.extractors import (
    withdraw_summary_extractor,
    withdraw_plan_extractor,
    policy_detail_extractor,
)


def test_withdraw_summary_extractor_returns_flat_data_from_rule_engine_result() -> None:
    context = {
        "_rule_engine_result": {
            "requested_amount": 10000,
            "total_available_excl_loan": 4029.63,
            "total_available_incl_loan": 6957.76,
            "options": [
                {"product_name": "鸿利04", "survival_fund_amt": 4000, "bonus_amt": 0, "loan_amt": 1493.63},
                {"product_name": "鑫利", "survival_fund_amt": 29.63, "bonus_amt": 0, "loan_amt": 1434.50},
            ],
        },
        "session_id": "s1",
    }
    card_args = {"advice_text_1": "建议一", "advice_text_2": "建议二", "plan_button_text": "获取方案"}

    flat = withdraw_summary_extractor(context, card_args)

    assert flat["header_value"] == "¥ 6,957.76"
    assert flat["header_sub"] == "不含贷款可领金额：¥ 4,029.63"
    assert flat["requested_amount_display"] == "本次取款目标：¥ 10,000.00"
    assert "零成本" in flat["zero_cost_title"]
    assert flat["zero_cost_item_1_label"] != ""
    assert flat["zero_cost_item_1_value"] == "¥ 4,000.00"
    assert flat["zero_cost_item_2_value"] == "¥ 29.63"
    assert flat["loan_item_1_value"] == "¥ 1,493.63"
    assert flat["loan_item_2_value"] == "¥ 1,434.50"
    assert flat["advice_text_1"] == "建议一"
    assert flat["advice_text_2"] == "建议二"
    assert flat["plan_button_text"] == "获取方案"
    assert flat["plan_action_args"] == {"queryMsg": "获取方案"}
    # Sample-compliant tag/label format (spaces around tag text; no space before 可贷)
    assert flat["zero_cost_tag"] == " (不影响保障) "
    assert flat["loan_tag"] == " (需支付利息) "
    assert flat["loan_item_1_label"].endswith("可贷(年利率5%)") and " 可贷" not in flat["loan_item_1_label"]


def test_withdraw_summary_extractor_uses_fallback_when_card_args_empty() -> None:
    context = {
        "_rule_engine_result": {"total_available_excl_loan": 0, "total_available_incl_loan": 0, "options": []},
    }
    flat = withdraw_summary_extractor(context, None)

    assert flat["advice_text_1"] != ""
    assert "零成本" in flat["advice_text_1"] or "保障" in flat["advice_text_1"]
    assert flat["plan_button_text"] == "获取最优方案"
    assert flat["plan_action_args"]["queryMsg"] == "获取最优方案"


def test_withdraw_summary_extractor_raises_when_no_rule_engine_result() -> None:
    with pytest.raises(ValueError) as exc_info:
        withdraw_summary_extractor({}, None)
    assert "rule_engine" in str(exc_info.value)


def test_withdraw_summary_extractor_raises_when_rule_engine_result_invalid() -> None:
    # Pass a string that is not valid JSON -> JSONDecodeError; pass non-dict after parse -> ValueError
    with pytest.raises((ValueError, json.JSONDecodeError)):
        withdraw_summary_extractor({"_rule_engine_result": "not valid json"}, None)


def test_withdraw_summary_extractor_accepts_rule_engine_from_tool_results_by_name() -> None:
    context = {
        "_tool_results_by_name": {
            "rule_engine": {
                "total_available_excl_loan": 100,
                "total_available_incl_loan": 200,
                "options": [
                    {"product_name": "P", "survival_fund_amt": 100, "bonus_amt": 0, "loan_amt": 100},
                ],
            },
        },
    }
    flat = withdraw_summary_extractor(context, None)
    assert flat["header_value"] == "¥ 200.00"
    assert flat["zero_cost_item_1_value"] == "¥ 100.00"


def test_withdraw_summary_extractor_accepts_json_string_rule_engine_result() -> None:
    context = {
        "_rule_engine_result": json.dumps({
            "total_available_excl_loan": 50,
            "total_available_incl_loan": 50,
            "options": [],
        }),
    }
    flat = withdraw_summary_extractor(context, None)
    assert flat["header_value"] == "¥ 50.00"


# ----- withdraw_plan_extractor -----


def test_withdraw_plan_extractor_returns_flat_data_with_defaults() -> None:
    context = {
        "_rule_engine_result": {
            "options": [
                {"policy_id": "P1", "product_name": "鸿利04", "survival_fund_amt": 1000},
            ],
        },
    }
    flat = withdraw_plan_extractor(context, None)

    assert flat["page_title"] == "为您推荐的取款方案"
    assert flat["amount_unit"] == "元"
    assert flat["rec_amount"] in ("—", "0.00") or flat["rec_amount"].replace(",", "").replace(".", "").isdigit()
    assert "rec_title" in flat and "alt_title" in flat
    assert "queryMsg" in flat["rec_action_args"]
    assert "queryMsg" in flat["alt_action_args"]
    assert flat["prompt_text"] != ""


def test_withdraw_plan_extractor_uses_card_args_for_rec_alt() -> None:
    context = {
        "_rule_engine_result": {
            "options": [
                {"policy_id": "P-A", "product_name": "产品A", "survival_fund_amt": 2000},
                {"policy_id": "P-B", "product_name": "产品B", "loan_amt": 1000},
            ],
        },
    }
    card_args = {
        "rec_policy_id": "P-A",
        "rec_option_type": "survival_fund",
        "rec_amount": 1000,
        "alt_policy_id": "P-B",
        "alt_option_type": "policy_loan",
        "alt_amount": 500,
    }
    flat = withdraw_plan_extractor(context, card_args)

    assert flat["rec_amount"] == "1,000.00"
    assert flat["alt_amount"] == "500.00"
    assert "产品A" in flat["rec_policy"] or "P-A" in flat["rec_policy"]
    assert flat["rec_cost"] == "无"
    assert "年利率" in flat["alt_cost"]


def test_withdraw_plan_extractor_raises_when_no_rule_engine_data() -> None:
    with pytest.raises(ValueError) as exc_info:
        withdraw_plan_extractor({}, None)
    assert "rule_engine" in str(exc_info.value)


# ----- policy_detail_extractor -----


def test_policy_detail_extractor_one_policy_sets_p2_p3_hidden() -> None:
    context = {
        "_rule_engine_result": {
            "options": [
                {
                    "policy_id": "P1",
                    "product_name": "鸿利04",
                    "policy_year": 6,
                    "survival_fund_amt": 4000,
                    "bonus_amt": 0,
                    "loan_amt": 1493.63,
                    "refund_amt": 0,
                    "available_amount": 5493.63,
                },
            ],
        },
    }
    flat = policy_detail_extractor(context, None)

    assert flat["page_title"] == "您的保单详情"
    assert flat["p1_title"] == "鸿利04"
    assert flat["p1_total_value"] == "¥ 5,493.63"
    assert flat["p2_hidden"] is True
    assert flat["p3_hidden"] is True
    assert flat["p2_title"] == ""
    assert flat["p3_title"] == ""


def test_policy_detail_extractor_three_policies_shows_all_cards() -> None:
    context = {
        "_rule_engine_result": {
            "options": [
                {"policy_id": "P1", "product_name": "A", "policy_year": 1, "survival_fund_amt": 100, "bonus_amt": 0, "loan_amt": 0, "refund_amt": 0, "available_amount": 100},
                {"policy_id": "P2", "product_name": "B", "policy_year": 2, "survival_fund_amt": 200, "bonus_amt": 0, "loan_amt": 0, "refund_amt": 0, "available_amount": 200},
                {"policy_id": "P3", "product_name": "C", "policy_year": 3, "survival_fund_amt": 300, "bonus_amt": 0, "loan_amt": 0, "refund_amt": 0, "available_amount": 300},
            ],
        },
    }
    flat = policy_detail_extractor(context, None)

    assert flat["p1_title"] == "C"
    assert flat["p2_title"] == "B"
    assert flat["p3_title"] == "A"
    assert flat["p2_hidden"] is False
    assert flat["p3_hidden"] is False
    assert flat["p1_total_value"] == "¥ 300.00"
    assert flat["p2_total_value"] == "¥ 200.00"
    assert flat["p3_total_value"] == "¥ 100.00"


def test_policy_detail_extractor_empty_options_fills_placeholders() -> None:
    context = {"_rule_engine_result": {"options": []}}
    flat = policy_detail_extractor(context, None)

    assert flat["p1_title"] == ""
    assert flat["p2_hidden"] is True
    assert flat["p3_hidden"] is True
    assert flat["prompt_text"] != ""


def test_policy_detail_extractor_raises_when_no_policy_data() -> None:
    with pytest.raises(ValueError) as exc_info:
        policy_detail_extractor({}, None)
    assert "保单" in str(exc_info.value) or "rule_engine" in str(exc_info.value)


# ----- Integration: render_card with real insurance extractors -----


@pytest.fixture
def _minimal_rule_engine_context() -> dict:
    return {
        "_rule_engine_result": {
            "requested_amount": 1000,
            "total_available_excl_loan": 1000,
            "total_available_incl_loan": 1000,
            "options": [
                {
                    "policy_id": "P1",
                    "product_name": "测试产品",
                    "policy_year": 1,
                    "survival_fund_amt": 1000,
                    "bonus_amt": 0,
                    "loan_amt": 0,
                    "refund_amt": 0,
                    "available_amount": 1000,
                },
            ],
        },
    }


@pytest.mark.asyncio
async def test_insurance_render_card_all_three_types_render_successfully(
    _minimal_rule_engine_context: dict,
) -> None:
    """RenderCardTool with real insurance extractors + templates for all 3 card_types."""
    from pathlib import Path

    from ark_agentic.agents.insurance.a2ui.extractors import (
        policy_detail_extractor,
        withdraw_plan_extractor,
        withdraw_summary_extractor,
    )
    from ark_agentic.core.tools import RenderCardTool
    from ark_agentic.core.types import ToolCall

    template_root = (
        Path(__file__).resolve().parent.parent.parent.parent
        / "src"
        / "ark_agentic"
        / "agents"
        / "insurance"
        / "a2ui"
        / "templates"
    )
    tool = RenderCardTool(
        template_root=template_root,
        extractors={
            "withdraw_summary": withdraw_summary_extractor,
            "withdraw_plan": withdraw_plan_extractor,
            "policy_detail": policy_detail_extractor,
        },
    )
    ctx = {**_minimal_rule_engine_context, "session_id": "s1"}

    for card_type in ("withdraw_summary", "withdraw_plan", "policy_detail"):
        tc = ToolCall(id=f"tc-{card_type}", name="render_card", arguments={"card_type": card_type})
        result = await tool.execute(tc, ctx)
        assert not result.is_error, f"{card_type}: {result.content}"
        assert result.content.get("event") == "beginRendering"
        assert result.content.get("surfaceId", "").startswith(card_type)
        assert "components" in result.content and len(result.content["components"]) > 0
        assert "data" in result.content
