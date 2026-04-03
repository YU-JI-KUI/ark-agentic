"""Tests for the unified RenderA2UITool (blocks + card_type paths)."""

import json
from pathlib import Path

import pytest

from ark_agentic.core.a2ui import A2UIOutput, A2UITheme, PresetRegistry
from ark_agentic.core.tools.render_a2ui import BlocksConfig, RenderA2UITool, TemplateConfig
from ark_agentic.core.types import ToolCall, ToolResultType


_SAMPLE_DATA = {
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
            "loan_interest_rate": 0.05,
            "refund_amt": 42000,
            "refund_fee_rate": 0.0,
            "processing_time": "3-5个工作日",
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
            "loan_interest_rate": None,
            "refund_amt": 160000,
            "refund_fee_rate": 0.01,
            "processing_time": "3-5个工作日",
        },
    ],
}


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


from ark_agentic.core.a2ui.blocks import A2UIOutput


def _mock_extractor(context: dict, card_args: dict | None) -> A2UIOutput:
    return A2UIOutput(template_data={
        "header_title": "标题",
        "header_value": "¥ 0",
        "header_sub": "",
        "requested_amount_display": "—",
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
    })


@pytest.fixture
def full_tool() -> RenderA2UITool:
    """Tool with both blocks and card_type support."""
    return RenderA2UITool(
        blocks=BlocksConfig(),
        template=TemplateConfig(
            template_root=_template_root(),
            extractors={"withdraw_summary": _mock_extractor},
        ),
        group="insurance",
    )


@pytest.fixture
def preset_tool() -> RenderA2UITool:
    """Tool with only preset_type support."""

    def _demo_extractor(
        context: dict, card_args: dict | None
    ) -> A2UIOutput:
        return A2UIOutput(
            template_data={
                "template": "demo_card",
                "from_ctx": context.get("session_id", ""),
                "x": (card_args or {}).get("x", 0),
            },
            llm_digest="preset-digest",
        )

    reg = PresetRegistry().register("demo", _demo_extractor)
    return RenderA2UITool(preset=reg, group="test")


@pytest.fixture
def blocks_only_tool() -> RenderA2UITool:
    """Tool with only blocks support (no template_root)."""
    return RenderA2UITool(blocks=BlocksConfig(), group="insurance")


@pytest.fixture
def ctx():
    return {
        "_rule_engine_result": _SAMPLE_DATA,
        "session_id": "test-session-123",
    }


# ---- mutual exclusion ----


@pytest.mark.asyncio
async def test_both_blocks_and_card_type_error(full_tool, ctx):
    tc = ToolCall.create("render_a2ui", {
        "blocks": "[]",
        "card_type": "withdraw_summary",
    })
    result = await full_tool.execute(tc, ctx)
    assert result.is_error
    assert "互斥" in str(result.content)


@pytest.mark.asyncio
async def test_neither_blocks_nor_card_type_error(full_tool, ctx):
    tc = ToolCall.create("render_a2ui", {})
    result = await full_tool.execute(tc, ctx)
    assert result.is_error


# ---- blocks path (agent blocks) ----


@pytest.fixture
def agent_tool() -> RenderA2UITool:
    """Tool with insurance agent blocks and components."""
    from ark_agentic.agents.insurance.a2ui import INSURANCE_BLOCKS, INSURANCE_COMPONENTS
    return RenderA2UITool(
        blocks=BlocksConfig(
            agent_blocks=INSURANCE_BLOCKS,
            agent_components=INSURANCE_COMPONENTS,
            theme=A2UITheme(root_gap=16, root_padding=[16, 32, 16, 16]),
        ),
        template=TemplateConfig(
            template_root=_template_root(),
            extractors={"withdraw_summary": _mock_extractor},
        ),
        group="insurance",
        state_keys=("_rule_engine_result",),
    )


@pytest.mark.asyncio
async def test_blocks_basic_render(agent_tool, ctx):
    blocks = json.dumps([
        {"type": "Card", "data": {"children": [
            {"type": "SectionHeader", "data": {"title": "Test"}},
            {"type": "KVRow", "data": {
                "label": "Total",
                "value": {"get": "total_available_incl_loan", "format": "currency"},
            }},
        ]}},
    ])
    tc = ToolCall.create("render_a2ui", {"blocks": blocks})
    result = await agent_tool.execute(tc, context=ctx)
    assert not result.is_error
    assert result.content["event"] == "beginRendering"
    text_comps = [
        c for c in result.content["components"]
        if "Text" in c.get("component", {})
        and c["component"]["Text"].get("text", {}).get("literalString") == "¥ 252,800.00"
    ]
    assert len(text_comps) == 1


@pytest.mark.asyncio
async def test_blocks_invalid_json(agent_tool, ctx):
    tc = ToolCall.create("render_a2ui", {"blocks": "not json"})
    result = await agent_tool.execute(tc, context=ctx)
    assert result.is_error
    assert "JSON" in result.content


@pytest.mark.asyncio
async def test_blocks_not_array(agent_tool, ctx):
    tc = ToolCall.create("render_a2ui", {"blocks": '{"x":1}'})
    result = await agent_tool.execute(tc, context=ctx)
    assert result.is_error


@pytest.mark.asyncio
async def test_blocks_divider(agent_tool, ctx):
    blocks = json.dumps([{"type": "Divider", "data": {}}])
    tc = ToolCall.create("render_a2ui", {"blocks": blocks})
    result = await agent_tool.execute(tc, context=ctx)
    assert not result.is_error


@pytest.mark.asyncio
async def test_blocks_unknown_type_error(agent_tool, ctx):
    blocks = json.dumps([{"type": "FakeBlock", "data": {}}])
    tc = ToolCall.create("render_a2ui", {"blocks": blocks})
    result = await agent_tool.execute(tc, context=ctx)
    assert result.is_error


@pytest.mark.asyncio
async def test_blocks_with_surface_id(agent_tool, ctx, monkeypatch):
    monkeypatch.setenv("A2UI_STRICT_VALIDATION", "warn")
    blocks = json.dumps([{"type": "Divider", "data": {}}])
    tc = ToolCall.create("render_a2ui", {"blocks": blocks, "surface_id": "surf-1"})
    result = await agent_tool.execute(tc, context=ctx)
    assert not result.is_error
    assert result.content["event"] == "surfaceUpdate"
    assert result.content["surfaceId"] == "surf-1"


@pytest.mark.asyncio
async def test_blocks_without_surface_id(agent_tool, ctx):
    blocks = json.dumps([{"type": "Divider", "data": {}}])
    tc = ToolCall.create("render_a2ui", {"blocks": blocks})
    result = await agent_tool.execute(tc, context=ctx)
    assert not result.is_error
    assert result.content["event"] == "beginRendering"


# ---- card_type path ----


@pytest.mark.asyncio
async def test_card_type_success(full_tool):
    tc = ToolCall.create("render_a2ui", {
        "card_type": "withdraw_summary",
        "card_args": '{"advice_text_1":"建议1","advice_text_2":"建议2"}',
    })
    result = await full_tool.execute(tc, {"session_id": "s1"})
    assert not result.is_error
    assert result.result_type == ToolResultType.A2UI
    assert result.content["event"] == "beginRendering"
    assert result.content["data"]["advice_text_1"] == "建议1"


@pytest.mark.asyncio
async def test_card_type_invalid(full_tool):
    tc = ToolCall.create("render_a2ui", {"card_type": "unknown_type"})
    result = await full_tool.execute(tc, {})
    assert result.is_error
    assert "不支持的卡片类型" in str(result.content)


@pytest.mark.asyncio
async def test_card_type_invalid_args_json(full_tool):
    tc = ToolCall.create("render_a2ui", {
        "card_type": "withdraw_summary",
        "card_args": "{invalid}",
    })
    result = await full_tool.execute(tc, {"session_id": "s1"})
    assert result.is_error
    assert "JSON" in str(result.content)


@pytest.mark.asyncio
async def test_card_type_without_template_root(blocks_only_tool):
    tc = ToolCall.create("render_a2ui", {"card_type": "withdraw_summary"})
    result = await blocks_only_tool.execute(tc, {})
    assert result.is_error
    assert "不可用" in str(result.content)


@pytest.mark.asyncio
async def test_card_type_extractor_raises():
    def failing(ctx, args):
        raise ValueError("no data")

    tool = RenderA2UITool(
        template=TemplateConfig(
            template_root=_template_root(),
            extractors={"withdraw_summary": failing},
        ),
    )
    tc = ToolCall.create("render_a2ui", {"card_type": "withdraw_summary"})
    result = await tool.execute(tc, {"session_id": "s1"})
    assert result.is_error
    assert "数据提取失败" in str(result.content)


@pytest.mark.asyncio
async def test_card_type_empty_args_ok(full_tool):
    tc = ToolCall.create("render_a2ui", {"card_type": "withdraw_summary"})
    result = await full_tool.execute(tc, {"session_id": "s1"})
    assert not result.is_error
    assert result.content["data"]["advice_text_1"] == "a1"


# ---- preset_type path ----


@pytest.mark.asyncio
async def test_preset_success_returns_template_data_as_content(preset_tool):
    tc = ToolCall.create(
        "render_a2ui",
        {"preset_type": "demo", "card_args": '{"x": 42}'},
    )
    result = await preset_tool.execute(tc, {"session_id": "sess-1"})
    assert not result.is_error
    assert result.result_type == ToolResultType.A2UI
    assert result.content["template"] == "demo_card"
    assert result.content["from_ctx"] == "sess-1"
    assert result.content["x"] == 42
    assert result.metadata.get("llm_digest") == "preset-digest"


@pytest.mark.asyncio
async def test_preset_invalid_type_returns_error(preset_tool):
    tc = ToolCall.create("render_a2ui", {"preset_type": "unknown"})
    result = await preset_tool.execute(tc, {})
    assert result.is_error
    assert "不支持的预设类型" in str(result.content)
    assert "demo" in str(result.content)


@pytest.mark.asyncio
async def test_preset_invalid_card_args_json(preset_tool):
    tc = ToolCall.create(
        "render_a2ui",
        {"preset_type": "demo", "card_args": "{bad"},
    )
    result = await preset_tool.execute(tc, {})
    assert result.is_error
    assert "JSON" in str(result.content)


@pytest.mark.asyncio
async def test_preset_extractor_raises_returns_error():
    def _fail(_ctx, _args):
        raise RuntimeError("boom")

    reg = PresetRegistry().register("bad", _fail)
    tool = RenderA2UITool(preset=reg)
    tc = ToolCall.create("render_a2ui", {"preset_type": "bad"})
    result = await tool.execute(tc, {})
    assert result.is_error
    assert "数据提取失败" in str(result.content)


@pytest.mark.asyncio
async def test_preset_blocks_mutually_exclusive():
    reg = PresetRegistry().register(
        "p",
        lambda _c, _a: A2UIOutput(template_data={"ok": True}),
    )
    tool = RenderA2UITool(blocks=BlocksConfig(), preset=reg)
    tc = ToolCall.create(
        "render_a2ui",
        {"preset_type": "p", "blocks": "[]"},
    )
    result = await tool.execute(tc, {})
    assert result.is_error
    assert "互斥" in str(result.content)


def test_preset_only_schema_has_preset_type_not_surface_id(preset_tool):
    schema = preset_tool.get_json_schema()
    props = schema["function"]["parameters"]["properties"]
    assert "preset_type" in props
    assert props["preset_type"].get("enum") == ["demo"]
    assert "card_type" not in props
    assert "blocks" not in props
    assert "surface_id" not in props


# ---- validation ----


@pytest.mark.asyncio
async def test_enforce_mode_returns_error(agent_tool, ctx, monkeypatch):
    monkeypatch.setenv("A2UI_STRICT_VALIDATION", "enforce")
    blocks = json.dumps([{"type": "Divider", "data": {}}])
    tc = ToolCall.create("render_a2ui", {"blocks": blocks})

    from unittest.mock import patch
    with patch(
        "ark_agentic.core.a2ui.guard.validate_event_payload",
        side_effect=ValueError("Mocked contract error"),
    ):
        result = await agent_tool.execute(tc, context=ctx)
        assert result.is_error
        assert "Mocked contract error" in result.content


@pytest.mark.asyncio
async def test_warn_mode_returns_a2ui(agent_tool, ctx, monkeypatch):
    monkeypatch.setenv("A2UI_STRICT_VALIDATION", "warn")
    blocks = json.dumps([{"type": "Divider", "data": {}}])
    tc = ToolCall.create("render_a2ui", {"blocks": blocks})

    from unittest.mock import patch
    with patch(
        "ark_agentic.core.a2ui.guard.validate_event_payload",
        side_effect=ValueError("Mocked contract error"),
    ):
        result = await agent_tool.execute(tc, context=ctx)
        assert not result.is_error
        assert result.content["event"] == "beginRendering"
        assert "warnings" in result.metadata


# ---- schema ----


def test_schema_has_expected_params(full_tool):
    schema = full_tool.get_json_schema()
    params = schema["function"]["parameters"]
    assert "blocks" in params["properties"]
    assert "card_type" in params["properties"]
    assert "card_args" in params["properties"]
    assert "surface_id" in params["properties"]
    assert "transforms" not in params["properties"]
    assert params["properties"]["card_type"].get("enum") == ["withdraw_summary"]
