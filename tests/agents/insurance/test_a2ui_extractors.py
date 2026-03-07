"""Tests for insurance a2ui extractors (withdraw_summary_extractor)."""

import json

import pytest

from ark_agentic.agents.insurance.a2ui.extractors import withdraw_summary_extractor


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
