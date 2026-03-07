"""Tests for core.a2ui.render_from_template."""

import json
from pathlib import Path

import pytest

from ark_agentic.core.a2ui import render_from_template


def _template_root() -> Path:
    return (
        Path(__file__).resolve().parent.parent.parent
        / "src"
        / "ark_agentic"
        / "agents"
        / "insurance"
        / "a2ui"
        / "templates"
    )


def test_render_from_template_returns_begin_rendering_and_merged_data() -> None:
    root = _template_root()
    data = {
        "header_title": "标题",
        "header_value": "¥ 1,234.56",
        "header_sub": "副标题",
        "requested_amount_display": "本次取款目标：¥ 5,000.00",
        "section_marker": "|",
        "zero_cost_title": "零成本",
        "zero_cost_tag": "",
        "zero_cost_total": "合计：¥ 0",
        "zero_cost_item_1_label": "",
        "zero_cost_item_1_value": "",
        "zero_cost_item_2_label": "",
        "zero_cost_item_2_value": "",
        "loan_title": "贷款",
        "loan_tag": "",
        "loan_total": "¥ 0",
        "loan_item_1_label": "",
        "loan_item_1_value": "",
        "loan_item_2_label": "",
        "loan_item_2_value": "",
        "advice_icon": "💡",
        "advice_title": "建议",
        "advice_text_1": "建议一",
        "advice_text_2": "建议二",
        "plan_button_text": "获取方案",
        "plan_action_args": {"queryMsg": "获取方案"},
    }
    out = render_from_template(root, "withdraw_summary", data, "session-abc")

    assert out["event"] == "beginRendering"
    assert out["version"] == "1.0.0"
    assert out["surfaceId"].startswith("withdraw_summary-")
    assert "session" in out["surfaceId"] or len(out["surfaceId"]) > 20
    assert out["rootComponentId"] == "root-001"
    assert len(out["components"]) > 0
    assert out["data"]["header_title"] == "标题"
    assert out["data"]["header_value"] == "¥ 1,234.56"
    assert out["data"]["advice_text_1"] == "建议一"
    assert out["data"]["plan_action_args"] == {"queryMsg": "获取方案"}


def test_render_from_template_injects_surface_id_with_session_prefix() -> None:
    root = _template_root()
    out = render_from_template(root, "withdraw_summary", {"header_title": "x", "header_value": "¥ 0", "header_sub": "", "requested_amount_display": "", "section_marker": "|", "zero_cost_title": "", "zero_cost_tag": "", "zero_cost_total": "", "zero_cost_item_1_label": "", "zero_cost_item_1_value": "", "zero_cost_item_2_label": "", "zero_cost_item_2_value": "", "loan_title": "", "loan_tag": "", "loan_total": "", "loan_item_1_label": "", "loan_item_1_value": "", "loan_item_2_label": "", "loan_item_2_value": "", "advice_icon": "", "advice_title": "", "advice_text_1": "", "advice_text_2": "", "plan_button_text": "", "plan_action_args": {}}, "sid123")
    assert out["surfaceId"].startswith("withdraw_summary-sid123")


def test_render_from_template_raises_file_not_found_for_missing_card_type() -> None:
    root = _template_root()
    with pytest.raises(FileNotFoundError) as exc_info:
        render_from_template(root, "nonexistent_card_type_xyz", {}, "")
    assert "nonexistent_card_type_xyz" in str(exc_info.value)


def test_render_from_template_overwrites_template_data_with_input_data() -> None:
    root = _template_root()
    # Template has data: {}; we pass header_title
    data = {
        "header_title": "覆盖标题",
        "header_value": "¥ 0",
        "header_sub": "",
        "requested_amount_display": "",
        "section_marker": "|",
        "zero_cost_title": "",
        "zero_cost_tag": "",
        "zero_cost_total": "",
        "zero_cost_item_1_label": "",
        "zero_cost_item_1_value": "",
        "zero_cost_item_2_label": "",
        "zero_cost_item_2_value": "",
        "loan_title": "",
        "loan_tag": "",
        "loan_total": "",
        "loan_item_1_label": "",
        "loan_item_1_value": "",
        "loan_item_2_label": "",
        "loan_item_2_value": "",
        "advice_icon": "",
        "advice_title": "",
        "advice_text_1": "",
        "advice_text_2": "",
        "plan_button_text": "",
        "plan_action_args": {},
    }
    out = render_from_template(root, "withdraw_summary", data, "")
    assert out["data"]["header_title"] == "覆盖标题"
