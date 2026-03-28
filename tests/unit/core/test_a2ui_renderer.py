"""Tests for core.a2ui.render_from_template."""

import json
from pathlib import Path

import pytest

from ark_agentic.core.a2ui import render_from_template


def _template_root() -> Path:
    return (
        Path(__file__).resolve().parents[3]
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
        "zero_cost_hide": False,
        "zero_cost_title": "零成本",
        "zero_cost_tag": "",
        "zero_cost_total": "合计：¥ 0",
        "zero_cost_items": [],
        "loan_hide": True,
        "loan_title": "贷款",
        "loan_tag": "",
        "loan_total": "¥ 0",
        "loan_items": [],
        "partial_surrender_hide": True,
        "partial_surrender_title": "",
        "partial_surrender_tag": "",
        "partial_surrender_total": "",
        "partial_surrender_items": [],
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
    assert out["data"]["zero_cost_hide"] is False
    assert out["data"]["loan_hide"] is True


def test_render_from_template_injects_surface_id_with_session_prefix() -> None:
    root = _template_root()
    minimal = {
        "header_title": "x", "header_value": "¥ 0", "header_sub": "", "requested_amount_display": "",
        "section_marker": "|",
        "zero_cost_hide": True, "zero_cost_title": "", "zero_cost_tag": "", "zero_cost_total": "", "zero_cost_items": [],
        "loan_hide": True, "loan_title": "", "loan_tag": "", "loan_total": "", "loan_items": [],
        "partial_surrender_hide": True, "partial_surrender_title": "", "partial_surrender_tag": "", "partial_surrender_total": "", "partial_surrender_items": [],
    }
    out = render_from_template(root, "withdraw_summary", minimal, "sid123")
    assert out["surfaceId"].startswith("withdraw_summary-sid123")


def test_render_from_template_raises_file_not_found_for_missing_card_type() -> None:
    root = _template_root()
    with pytest.raises(FileNotFoundError) as exc_info:
        render_from_template(root, "nonexistent_card_type_xyz", {}, "")
    assert "nonexistent_card_type_xyz" in str(exc_info.value)


def test_render_from_template_overwrites_template_data_with_input_data() -> None:
    root = _template_root()
    data = {
        "header_title": "覆盖标题",
        "header_value": "¥ 0",
        "header_sub": "",
        "requested_amount_display": "",
        "section_marker": "|",
        "zero_cost_hide": True, "zero_cost_title": "", "zero_cost_tag": "", "zero_cost_total": "", "zero_cost_items": [],
        "loan_hide": True, "loan_title": "", "loan_tag": "", "loan_total": "", "loan_items": [],
        "partial_surrender_hide": True, "partial_surrender_title": "", "partial_surrender_tag": "", "partial_surrender_total": "", "partial_surrender_items": [],
    }
    out = render_from_template(root, "withdraw_summary", data, "")
    assert out["data"]["header_title"] == "覆盖标题"
