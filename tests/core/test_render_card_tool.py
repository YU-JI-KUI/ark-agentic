"""Tests for core.tools.RenderCardTool and CardExtractor."""

import pytest
from pathlib import Path

from ark_agentic.core.tools import RenderCardTool
from ark_agentic.core.types import ToolCall, ToolResultType


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


def _mock_extractor(context: dict, card_args: dict | None) -> dict:
    """Extractor that returns minimal flat data for withdraw_summary template."""
    out = {
        "header_title": "标题",
        "header_value": "¥ 0",
        "header_sub": "",
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
        "advice_icon": "💡",
        "advice_title": "",
        "advice_text_1": (card_args or {}).get("advice_text_1", "a1"),
        "advice_text_2": (card_args or {}).get("advice_text_2", "a2"),
        "plan_button_text": (card_args or {}).get("plan_button_text", "获取"),
        "plan_action_args": {"queryMsg": (card_args or {}).get("plan_action_query", "获取")},
    }
    return out


@pytest.fixture
def tool() -> RenderCardTool:
    return RenderCardTool(
        template_root=_template_root(),
        extractors={"withdraw_summary": _mock_extractor},
    )


def test_render_card_tool_schema_has_card_type_enum(tool: RenderCardTool) -> None:
    schema = tool.get_json_schema()
    params = schema["function"]["parameters"]
    assert "card_type" in params["properties"]
    assert params["properties"]["card_type"].get("enum") == ["withdraw_summary"]
    assert "card_args" in params["properties"]


@pytest.mark.asyncio
async def test_render_card_tool_execute_success(tool: RenderCardTool) -> None:
    tc = ToolCall(
        id="tc1",
        name="render_card",
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
    assert result.content["data"]["advice_text_1"] == "建议1"
    assert result.content["data"]["advice_text_2"] == "建议2"


@pytest.mark.asyncio
async def test_render_card_tool_execute_invalid_card_type_returns_error(tool: RenderCardTool) -> None:
    tc = ToolCall(id="tc2", name="render_card", arguments={"card_type": "unknown_type"})
    result = await tool.execute(tc, {})

    assert result.is_error
    assert "不支持的卡片类型" in str(result.content)
    assert "unknown_type" in str(result.content)


@pytest.mark.asyncio
async def test_render_card_tool_execute_invalid_card_args_json_returns_error(tool: RenderCardTool) -> None:
    tc = ToolCall(
        id="tc3",
        name="render_card",
        arguments={"card_type": "withdraw_summary", "card_args": "{invalid}"},
    )
    result = await tool.execute(tc, {"session_id": "s1"})

    assert result.is_error
    assert "JSON" in str(result.content)


@pytest.mark.asyncio
async def test_render_card_tool_execute_extractor_raises_returns_error() -> None:
    def failing_extractor(_ctx: dict, _args: dict | None) -> dict:
        raise ValueError("no data")

    t = RenderCardTool(
        template_root=_template_root(),
        extractors={"withdraw_summary": failing_extractor},
    )
    tc = ToolCall(id="tc4", name="render_card", arguments={"card_type": "withdraw_summary"})
    result = await t.execute(tc, {"session_id": "s1"})

    assert result.is_error
    assert "no data" in str(result.content) or "数据提取失败" in str(result.content)


@pytest.mark.asyncio
async def test_render_card_tool_execute_empty_card_args_ok(tool: RenderCardTool) -> None:
    tc = ToolCall(id="tc5", name="render_card", arguments={"card_type": "withdraw_summary"})
    result = await tool.execute(tc, {"session_id": "s1"})

    assert not result.is_error
    assert result.content["data"]["advice_text_1"] == "a1"
    assert result.content["data"]["advice_text_2"] == "a2"
