"""Tests for A2UI Block Composer: block builders, composer, tool, skill loader."""

import json
import textwrap

import pytest

from ark_agentic.core.a2ui.blocks import (
    resolve_binding,
    _resolve_action,
    get_block_builder,
    get_block_types,
    _BLOCK_REGISTRY,
    CARD_BG,
    PAGE_BG,
)
from ark_agentic.core.a2ui.composer import BlockComposer
from ark_agentic.core.tools.render_a2ui import RenderA2UITool
from ark_agentic.core.types import ToolCall


# ============ resolve_binding ============


class TestResolveBinding:
    def test_dollar_shorthand(self):
        assert resolve_binding("$field") == {"path": "field"}

    def test_plain_string(self):
        assert resolve_binding("hello") == {"literalString": "hello"}

    def test_dict_path_passthrough(self):
        v = {"path": "x.y"}
        assert resolve_binding(v) is v

    def test_dict_literal_passthrough(self):
        v = {"literalString": "ok"}
        assert resolve_binding(v) is v

    def test_number(self):
        assert resolve_binding(42) == {"literalString": 42}

    def test_bool(self):
        assert resolve_binding(True) == {"literalString": True}

    def test_list(self):
        assert resolve_binding([1, 2]) == {"literalString": [1, 2]}

    def test_dict_no_path_or_literal(self):
        assert resolve_binding({"a": 1}) == {"literalString": {"a": 1}}


class TestResolveAction:
    def test_non_dict(self):
        assert _resolve_action("click") == "click"

    def test_args_resolved(self):
        result = _resolve_action({"name": "query", "args": "$params"})
        assert result["args"] == {"path": "params"}


# ============ Block Registry ============


class TestBlockRegistry:
    def test_registry_empty_after_clear(self):
        assert set(_BLOCK_REGISTRY.keys()) == set()

    def test_get_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown block type"):
            get_block_builder("NonExistent")

    def test_get_block_types(self):
        types = get_block_types()
        assert isinstance(types, frozenset)
        assert len(types) == 0


# ============ Block Builders (insurance agent) ============


def _id_gen():
    counter = [0]

    def gen(prefix: str) -> str:
        counter[0] += 1
        return f"{prefix.lower()}-{counter[0]:03d}"
    return gen


class TestInsuranceBlocks:
    def test_section_header_basic(self):
        from ark_agentic.agents.insurance.a2ui.blocks import build_section_header
        comps = build_section_header({"title": "Test"}, _id_gen())
        assert len(comps) >= 3
        assert "Row" in comps[0]["component"]

    def test_section_header_with_tag(self):
        from ark_agentic.agents.insurance.a2ui.blocks import build_section_header
        comps = build_section_header({"title": "Test", "tag": "tag1", "tag_color": "#123"}, _id_gen())
        tag_comps = [c for c in comps if "Tag" in c.get("component", {})]
        assert len(tag_comps) == 1

    def test_kv_row(self):
        from ark_agentic.agents.insurance.a2ui.blocks import build_kv_row
        comps = build_kv_row({"label": "L", "value": "V"}, _id_gen())
        assert len(comps) == 3
        assert "Row" in comps[0]["component"]

    def test_accent_total_with_label(self):
        from ark_agentic.agents.insurance.a2ui.blocks import build_accent_total
        comps = build_accent_total({"label": "Total", "value": "¥1000"}, _id_gen())
        assert len(comps) == 3
        assert "Row" in comps[0]["component"]

    def test_accent_total_without_label(self):
        from ark_agentic.agents.insurance.a2ui.blocks import build_accent_total
        comps = build_accent_total({"value": "¥1000"}, _id_gen())
        assert len(comps) == 1
        assert "Text" in comps[0]["component"]

    def test_hint_text(self):
        from ark_agentic.agents.insurance.a2ui.blocks import build_hint_text
        comps = build_hint_text({"text": "hint"}, _id_gen())
        assert len(comps) == 1
        assert "Text" in comps[0]["component"]

    def test_action_button(self):
        from ark_agentic.agents.insurance.a2ui.blocks import build_action_button
        comps = build_action_button(
            {"text": "Go", "action": {"name": "query", "args": {"queryMsg": "test"}}},
            _id_gen(),
        )
        assert len(comps) == 1
        btn = comps[0]["component"]["Button"]
        assert btn["type"] == "primary"
        assert btn["width"] == 100

    def test_divider(self):
        from ark_agentic.agents.insurance.a2ui.blocks import build_divider
        comps = build_divider({}, _id_gen())
        assert len(comps) == 1
        assert "Divider" in comps[0]["component"]


# ============ BlockComposer ============


class TestBlockComposer:
    def test_compose_empty_blocks(self):
        composer = BlockComposer()
        payload = composer.compose([], {})
        col = payload["components"][0]["component"]["Column"]
        assert col["children"]["explicitList"] == []

    def test_compose_surface_id(self):
        composer = BlockComposer()
        payload = composer.compose([], {}, surface_id="my-surface")
        assert payload["surfaceId"] == "my-surface"

    def test_root_gap_and_padding(self):
        composer = BlockComposer()
        payload = composer.compose([], {}, root_gap=16, root_padding=[16, 32, 16, 16])
        col = payload["components"][0]["component"]["Column"]
        assert col["gap"] == 16
        assert col["padding"] == [16, 32, 16, 16]


# ============ Tool Integration ============


class TestRenderA2UITool:
    @pytest.fixture
    def tool(self):
        return RenderA2UITool()

    @pytest.mark.asyncio
    async def test_invalid_blocks_json(self, tool):
        tc = ToolCall.create("render_a2ui", {"blocks": "not-json"})
        result = await tool.execute(tc, context={})
        assert result.is_error

    @pytest.mark.asyncio
    async def test_blocks_not_array(self, tool):
        tc = ToolCall.create("render_a2ui", {"blocks": '{"x":1}'})
        result = await tool.execute(tc, context={})
        assert result.is_error

    @pytest.mark.asyncio
    async def test_unknown_block_type(self, tool):
        tc = ToolCall.create(
            "render_a2ui",
            {"blocks": json.dumps([{"type": "FakeBlock", "data": {}}])},
        )
        result = await tool.execute(tc, context={})
        assert result.is_error
