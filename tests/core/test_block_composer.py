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
from ark_agentic.core.tools.render_dynamic_card import RenderDynamicCardTool
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
    def test_all_blocks_registered(self):
        expected = {
            "SummaryHeader", "SectionCard", "InfoCard", "AdviceCard",
            "KeyValueList", "DataTable", "ItemList", "ActionButton",
            "ButtonGroup", "Divider", "TagRow", "ImageBanner", "StatusRow",
            "FundsSummary",
        }
        assert expected == set(_BLOCK_REGISTRY.keys())

    def test_get_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown block type"):
            get_block_builder("NonExistent")

    def test_get_block_types(self):
        types = get_block_types()
        assert isinstance(types, frozenset)
        assert "SummaryHeader" in types


# ============ Block Builders ============


def _id_gen():
    counter = [0]

    def gen(prefix: str) -> str:
        counter[0] += 1
        return f"{prefix.lower()}-{counter[0]:03d}"
    return gen


class TestSummaryHeaderBuilder:
    def test_basic(self):
        builder = get_block_builder("SummaryHeader")
        comps = builder({"title": "$t", "value": "$v"}, _id_gen())
        assert len(comps) >= 3
        card = comps[0]
        assert "Card" in card["component"]
        assert card["component"]["Card"]["backgroundColor"] == CARD_BG

    def test_with_subtitle_and_note(self):
        builder = get_block_builder("SummaryHeader")
        comps = builder(
            {"title": "T", "value": "V", "subtitle": "S", "note": "N"},
            _id_gen(),
        )
        assert len(comps) >= 5


class TestSectionCardBuilder:
    def test_basic(self):
        builder = get_block_builder("SectionCard")
        comps = builder(
            {"title": "Title", "total": "$total", "items": "$items"},
            _id_gen(),
        )
        assert len(comps) >= 6
        card = comps[0]
        assert "Card" in card["component"]

    def test_with_tag(self):
        builder = get_block_builder("SectionCard")
        comps = builder(
            {"title": "T", "tag": "tag", "total": "$t", "items": "$i"},
            _id_gen(),
        )
        text_tag = {"literalString": "tag"}
        assert any(
            c.get("component", {}).get("Text", {}).get("text") == text_tag
            for c in comps
        )


class TestInfoCardBuilder:
    def test_basic(self):
        comps = get_block_builder("InfoCard")(
            {"title": "Hello", "body": "$msg"}, _id_gen()
        )
        assert len(comps) == 4
        assert "Card" in comps[0]["component"]


class TestAdviceCardBuilder:
    def test_with_icon(self):
        comps = get_block_builder("AdviceCard")(
            {"icon": "💡", "title": "Tips", "texts": ["a", "b"]}, _id_gen()
        )
        assert len(comps) >= 5

    def test_without_icon(self):
        comps = get_block_builder("AdviceCard")(
            {"title": "Tips", "texts": ["a"]}, _id_gen()
        )
        assert len(comps) >= 4


class TestActionButtonBuilder:
    def test_basic(self):
        comps = get_block_builder("ActionButton")(
            {"text": "Go", "action": {"name": "query", "args": "$a"}},
            _id_gen(),
        )
        assert len(comps) == 1
        btn = comps[0]["component"]["Button"]
        assert btn["type"] == "primary"
        assert btn["action"]["args"] == {"path": "a"}


class TestDividerBuilder:
    def test_basic(self):
        comps = get_block_builder("Divider")({}, _id_gen())
        assert len(comps) == 1
        assert "Divider" in comps[0]["component"]


class TestStatusRowBuilder:
    def test_basic(self):
        comps = get_block_builder("StatusRow")(
            {"label": "Status", "value": "OK", "status": "success"}, _id_gen()
        )
        assert len(comps) == 4
        circle = comps[1]["component"]["Circle"]
        assert circle["backgroundColor"] == "#33CC66"


# ============ BlockComposer ============


class TestBlockComposer:
    def test_compose_basic(self):
        composer = BlockComposer()
        blocks = [
            {"type": "InfoCard", "data": {"title": "$t", "body": "$b"}},
            {"type": "ActionButton", "data": {"text": "Go"}},
        ]
        data = {"t": "Hello", "b": "World"}
        payload = composer.compose(blocks, data, session_id="abc12345")
        assert payload["event"] == "beginRendering"
        assert payload["version"] == "1.0.0"
        assert payload["data"] == data
        assert len(payload["components"]) >= 3
        root = payload["components"][0]
        assert "Column" in root["component"]
        assert root["component"]["Column"]["backgroundColor"] == PAGE_BG

    def test_compose_surface_id(self):
        composer = BlockComposer()
        payload = composer.compose(
            [{"type": "Divider", "data": {}}],
            {},
            surface_id="my-surface",
        )
        assert payload["surfaceId"] == "my-surface"

    def test_compose_empty_blocks(self):
        composer = BlockComposer()
        payload = composer.compose([], {})
        col = payload["components"][0]["component"]["Column"]
        assert col["children"]["explicitList"] == []

    def test_root_component_id(self):
        composer = BlockComposer()
        payload = composer.compose(
            [{"type": "Divider", "data": {}}], {}
        )
        assert payload["rootComponentId"] == payload["components"][0]["id"]


# ============ Tool Integration ============


class TestRenderDynamicCardTool:
    @pytest.fixture
    def tool(self):
        return RenderDynamicCardTool()

    @pytest.mark.asyncio
    async def test_basic_blocks(self, tool):
        blocks = [
            {"type": "InfoCard", "data": {"title": "$title", "body": "$body"}},
        ]
        transforms = {
            "title": {"literal": "Test"},
            "body": {"literal": "Body text"},
        }
        tc = ToolCall.create(
            "render_dynamic_card",
            {
                "blocks": json.dumps(blocks),
                "transforms": json.dumps(transforms),
            },
        )
        result = await tool.execute(tc, context={})
        assert not result.is_error
        payload = result.content
        assert payload["event"] == "beginRendering"
        assert len(payload["components"]) >= 3

    @pytest.mark.asyncio
    async def test_invalid_blocks_json(self, tool):
        tc = ToolCall.create("render_dynamic_card", {"blocks": "not-json"})
        result = await tool.execute(tc, context={})
        assert result.is_error

    @pytest.mark.asyncio
    async def test_blocks_not_array(self, tool):
        tc = ToolCall.create("render_dynamic_card", {"blocks": '{"x":1}'})
        result = await tool.execute(tc, context={})
        assert result.is_error

    @pytest.mark.asyncio
    async def test_unknown_block_type(self, tool):
        tc = ToolCall.create(
            "render_dynamic_card",
            {"blocks": json.dumps([{"type": "FakeBlock", "data": {}}])},
        )
        result = await tool.execute(tc, context={})
        assert result.is_error

    @pytest.mark.asyncio
    async def test_data_model_update(self, tool):
        tc = ToolCall.create(
            "render_dynamic_card",
            {
                "blocks": "[]",
                "event": "dataModelUpdate",
                "surface_id": "s1",
            },
        )
        result = await tool.execute(tc, context={})
        assert not result.is_error
        assert result.content["event"] == "dataModelUpdate"

    @pytest.mark.asyncio
    async def test_delete_surface(self, tool):
        tc = ToolCall.create(
            "render_dynamic_card",
            {"blocks": "[]", "event": "deleteSurface", "surface_id": "s1"},
        )
        result = await tool.execute(tc, context={})
        assert not result.is_error
        assert result.content["event"] == "deleteSurface"

    @pytest.mark.asyncio
    async def test_transforms_from_context(self, tool):
        blocks = [{"type": "InfoCard", "data": {"title": "$t", "body": "$b"}}]
        transforms = {
            "t": {"get": "total_available_incl_loan", "format": "currency"},
            "b": {"literal": "ok"},
        }
        ctx = {
            "_rule_engine_result": {"total_available_incl_loan": 12345},
        }
        tc = ToolCall.create(
            "render_dynamic_card",
            {
                "blocks": json.dumps(blocks),
                "transforms": json.dumps(transforms),
            },
        )
        result = await tool.execute(tc, context=ctx)
        assert not result.is_error
        assert "12,345" in str(result.content["data"].get("t", ""))

    @pytest.mark.asyncio
    async def test_policy_query_data_via_state_delta(self, tool):
        """policy_query results stored in _policy_query_result are merged at top level."""
        blocks = [{"type": "InfoCard", "data": {"title": "$t", "body": "$b"}}]
        transforms = {
            "t": {"get": "total_count"},
            "b": {"literal": "ok"},
        }
        ctx = {
            "_policy_query_result": {
                "policyAssertList": [{"policy_id": "P1"}],
                "total_count": 3,
            },
        }
        tc = ToolCall.create(
            "render_dynamic_card",
            {"blocks": json.dumps(blocks), "transforms": json.dumps(transforms)},
        )
        result = await tool.execute(tc, context=ctx)
        assert not result.is_error
        assert result.content["data"]["t"] == 3

    @pytest.mark.asyncio
    async def test_customer_info_data_via_state_delta(self, tool):
        """customer_info results stored in _customer_info_result are merged at top level."""
        blocks = [{"type": "InfoCard", "data": {"title": "$t", "body": "$b"}}]
        transforms = {
            "t": {"get": "identity.name"},
            "b": {"get": "contact.phone"},
        }
        ctx = {
            "_customer_info_result": {
                "identity": {"name": "张明"},
                "contact": {"phone": "138****5678"},
            },
        }
        tc = ToolCall.create(
            "render_dynamic_card",
            {"blocks": json.dumps(blocks), "transforms": json.dumps(transforms)},
        )
        result = await tool.execute(tc, context=ctx)
        assert not result.is_error
        assert result.content["data"]["t"] == "张明"
        assert result.content["data"]["b"] == "138****5678"

    @pytest.mark.asyncio
    async def test_same_turn_tool_results_merged_at_top_level(self, tool):
        """Same-turn _tool_results_by_name are merged at top level (no _tool_ prefix)."""
        blocks = [{"type": "InfoCard", "data": {"title": "$t", "body": "$b"}}]
        transforms = {
            "t": {"get": "identity.name"},
            "b": {"get": "total_count"},
        }
        ctx = {
            "_tool_results_by_name": {
                "customer_info": {"identity": {"name": "李四"}},
                "policy_query": {"policyAssertList": [], "total_count": 5},
            },
        }
        tc = ToolCall.create(
            "render_dynamic_card",
            {"blocks": json.dumps(blocks), "transforms": json.dumps(transforms)},
        )
        result = await tool.execute(tc, context=ctx)
        assert not result.is_error
        assert result.content["data"]["t"] == "李四"
        assert result.content["data"]["b"] == 5


class TestKeyValueListRowMode:
    """KeyValueList row mode produces nested bindings that the renderer must recursively resolve."""

    def test_row_mode_produces_nested_bindings(self):
        builder = get_block_builder("KeyValueList")
        comps = builder({"rowCount": 3, "rowPrefix": "r"}, _id_gen())
        list_comp = next(c for c in comps if "List" in c.get("component", {}))
        ds = list_comp["component"]["List"]["dataSource"]
        assert "literalString" in ds
        items = ds["literalString"]
        assert len(items) == 3
        assert items[0] == {"label": {"path": "r1_label"}, "value": {"path": "r1_value"}}
        assert items[2] == {"label": {"path": "r3_label"}, "value": {"path": "r3_value"}}

    def test_default_row_count_and_prefix(self):
        builder = get_block_builder("KeyValueList")
        comps = builder({}, _id_gen())
        list_comp = next(c for c in comps if "List" in c.get("component", {}))
        items = list_comp["component"]["List"]["dataSource"]["literalString"]
        assert len(items) == 9
        assert items[0]["label"] == {"path": "row1_label"}


class TestDataTableWidthNormalization:
    """DataTable column widths must produce valid CSS units."""

    def test_numeric_widths_become_percent(self):
        builder = get_block_builder("DataTable")
        comps = builder(
            {
                "columns": [
                    {"header": "A", "field": "a", "width": 40},
                    {"header": "B", "field": "b", "width": 30},
                    {"header": "C", "field": "c", "width": 30},
                ],
                "data": "$rows",
            },
            _id_gen(),
        )
        table_comp = next(c for c in comps if "Table" in c.get("component", {}))
        widths = table_comp["component"]["Table"]["columnWidths"]
        assert widths == ["40%", "30%", "30%"]

    def test_string_widths_passthrough(self):
        builder = get_block_builder("DataTable")
        comps = builder(
            {
                "columns": [
                    {"header": "A", "field": "a", "width": "2fr"},
                    {"header": "B", "field": "b", "width": "1fr"},
                ],
                "data": "$rows",
            },
            _id_gen(),
        )
        table_comp = next(c for c in comps if "Table" in c.get("component", {}))
        widths = table_comp["component"]["Table"]["columnWidths"]
        assert widths == ["2fr", "1fr"]

    def test_default_width_is_1fr(self):
        builder = get_block_builder("DataTable")
        comps = builder(
            {
                "columns": [
                    {"header": "A", "field": "a"},
                    {"header": "B", "field": "b"},
                ],
                "data": "$rows",
            },
            _id_gen(),
        )
        table_comp = next(c for c in comps if "Table" in c.get("component", {}))
        widths = table_comp["component"]["Table"]["columnWidths"]
        assert widths == ["1fr", "1fr"]

    def test_mixed_numeric_and_string_widths(self):
        builder = get_block_builder("DataTable")
        comps = builder(
            {
                "columns": [
                    {"header": "A", "field": "a", "width": 50},
                    {"header": "B", "field": "b", "width": "1fr"},
                ],
                "data": "$rows",
            },
            _id_gen(),
        )
        table_comp = next(c for c in comps if "Table" in c.get("component", {}))
        widths = table_comp["component"]["Table"]["columnWidths"]
        assert widths == ["50%", "1fr"]


# ============ Skill Loader Mode Selection ============


class TestSkillLoaderModeSelection:
    @pytest.fixture
    def skill_dir(self, tmp_path):
        """Create skill dir with SKILL.md and SKILL_DYNAMIC_UI.md."""
        skill_a = tmp_path / "skill_a"
        skill_a.mkdir()
        (skill_a / "SKILL.md").write_text(textwrap.dedent("""\
            ---
            name: SkillA Template
            description: template version
            required_tools:
              - render_card
            ---
            Template content
        """))
        (skill_a / "SKILL_DYNAMIC_UI.md").write_text(textwrap.dedent("""\
            ---
            name: SkillA Dynamic
            description: dynamic version
            required_tools:
              - render_dynamic_card
            ---
            Dynamic content
        """))

        skill_b = tmp_path / "skill_b"
        skill_b.mkdir()
        (skill_b / "SKILL.md").write_text(textwrap.dedent("""\
            ---
            name: SkillB
            description: mode-agnostic
            ---
            Agnostic content
        """))

        skill_c = tmp_path / "skill_c"
        skill_c.mkdir()
        (skill_c / "SKILL_DYNAMIC_UI.md").write_text(textwrap.dedent("""\
            ---
            name: SkillC DynOnly
            description: dynamic-only skill
            required_tools:
              - render_dynamic_card
            ---
            Dynamic only
        """))

        return tmp_path

    def test_dynamic_mode_picks_dynamic_file(self, skill_dir):
        from ark_agentic.core.skills.base import SkillConfig
        from ark_agentic.core.skills.loader import SkillLoader

        config = SkillConfig(
            skill_directories=[str(skill_dir)],
            a2ui_mode="dynamic",
        )
        loader = SkillLoader(config)
        skills = loader.load_from_directories()

        skill_a = skills.get("skill_a")
        assert skill_a is not None
        assert skill_a.metadata.name == "SkillA Dynamic"
        assert "Dynamic content" in skill_a.content

        skill_b = skills.get("skill_b")
        assert skill_b is not None
        assert skill_b.metadata.name == "SkillB"

        skill_c = skills.get("skill_c")
        assert skill_c is not None
        assert skill_c.metadata.name == "SkillC DynOnly"

    def test_template_mode_picks_default_file(self, skill_dir):
        from ark_agentic.core.skills.base import SkillConfig
        from ark_agentic.core.skills.loader import SkillLoader

        config = SkillConfig(
            skill_directories=[str(skill_dir)],
            a2ui_mode="template",
        )
        loader = SkillLoader(config)
        skills = loader.load_from_directories()

        skill_a = skills.get("skill_a")
        assert skill_a is not None
        assert skill_a.metadata.name == "SkillA Template"

        skill_b = skills.get("skill_b")
        assert skill_b is not None

        # skill_c has no SKILL.md -> not loaded in template mode
        assert "skill_c" not in skills
