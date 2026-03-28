"""Tests for RenderA2UITool card_type path (insurance template.json + extractors)."""

import pytest
from pathlib import Path

from ark_agentic.core.tools.render_a2ui import RenderA2UITool
from ark_agentic.core.types import ToolCall, ToolResultType


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


def _mock_extractor(context: dict, card_args: dict | None) -> dict:
    """Extractor that returns minimal flat data for withdraw_summary template."""
    return {
        "header_title": "标题",
        "header_value": "¥ 0",
        "header_sub": "",
        "requested_amount_display": "—",
        "section_marker": "|",
        "zero_cost_hide": True,
        "zero_cost_title": "",
        "zero_cost_tag": "",
        "zero_cost_total": "",
        "zero_cost_items": [],
        "loan_hide": True,
        "loan_title": "",
        "loan_tag": "",
        "loan_total": "",
        "loan_items": [],
        "partial_surrender_hide": True,
        "partial_surrender_title": "",
        "partial_surrender_tag": "",
        "partial_surrender_total": "",
        "partial_surrender_items": [],
    }


@pytest.fixture
def tool() -> RenderA2UITool:
    return RenderA2UITool(
        template_root=_template_root(),
        extractors={"withdraw_summary": _mock_extractor},
    )


def test_render_a2ui_tool_schema_has_card_type_enum(tool: RenderA2UITool) -> None:
    schema = tool.get_json_schema()
    params = schema["function"]["parameters"]
    assert "card_type" in params["properties"]
    assert params["properties"]["card_type"].get("enum") == ["withdraw_summary"]
    assert "card_args" in params["properties"]


@pytest.mark.asyncio
async def test_render_a2ui_tool_execute_success(tool: RenderA2UITool) -> None:
    tc = ToolCall(
        id="tc1",
        name="render_a2ui",
        arguments={
            "card_type": "withdraw_summary",
            "card_args": '{"advice_text_1":"建议1","advice_text_2":"建议2"}',
        },
    )
    ctx = {"session_id": "s1"}
    result = await tool.execute(tc, ctx)

    assert not result.is_error
    assert result.result_type == ToolResultType.A2UI
    assert result.content["event"] == "beginRendering"
    assert len(result.content["components"]) > 0
    assert result.content["data"]["zero_cost_hide"] is True
    assert result.content["data"]["loan_hide"] is True
    assert result.content["data"]["header_title"] == "标题"


@pytest.mark.asyncio
async def test_render_a2ui_tool_execute_invalid_card_type_returns_error(tool: RenderA2UITool) -> None:
    tc = ToolCall(id="tc2", name="render_a2ui", arguments={"card_type": "unknown_type"})
    result = await tool.execute(tc, {})

    assert result.is_error
    assert "不支持的卡片类型" in str(result.content)
    assert "unknown_type" in str(result.content)


@pytest.mark.asyncio
async def test_render_a2ui_tool_execute_invalid_card_args_json_returns_error(tool: RenderA2UITool) -> None:
    tc = ToolCall(
        id="tc3",
        name="render_a2ui",
        arguments={"card_type": "withdraw_summary", "card_args": "{invalid}"},
    )
    result = await tool.execute(tc, {"session_id": "s1"})

    assert result.is_error
    assert "JSON" in str(result.content)


@pytest.mark.asyncio
async def test_render_a2ui_tool_execute_extractor_raises_returns_error() -> None:
    def failing_extractor(_ctx: dict, _args: dict | None) -> dict:
        raise ValueError("no data")

    t = RenderA2UITool(
        template_root=_template_root(),
        extractors={"withdraw_summary": failing_extractor},
    )
    tc = ToolCall(id="tc4", name="render_a2ui", arguments={"card_type": "withdraw_summary"})
    result = await t.execute(tc, {"session_id": "s1"})

    assert result.is_error
    assert "no data" in str(result.content) or "数据提取失败" in str(result.content)


@pytest.mark.asyncio
async def test_render_a2ui_tool_execute_empty_card_args_ok(tool: RenderA2UITool) -> None:
    tc = ToolCall(id="tc5", name="render_a2ui", arguments={"card_type": "withdraw_summary"})
    result = await tool.execute(tc, {"session_id": "s1"})

    assert not result.is_error
    assert result.content["data"]["partial_surrender_hide"] is True
    assert result.content["data"]["zero_cost_items"] == []
