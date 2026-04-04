"""Tests for A2UITheme: defaults, override, immutability, backward-compat aliases,
and integration with BlockComposer / RenderA2UITool."""

import json

import pytest
from pydantic import ValidationError

from ark_agentic.core.a2ui.theme import A2UITheme
from ark_agentic.core.a2ui import blocks as blocks_mod
from ark_agentic.core.a2ui.composer import BlockComposer
from ark_agentic.core.tools.render_a2ui import BlocksConfig, RenderA2UITool
from ark_agentic.core.types import ToolCall


# ============ A2UITheme unit tests ============


class TestA2UIThemeDefaults:
    """P0: default theme values match the original hardcoded constants."""

    def test_color_palette(self):
        t = A2UITheme()
        assert t.accent == "#FF6600"
        assert t.page_bg == "#F5F5F5"
        assert t.card_bg == "#FFFFFF"
        assert t.title_color == "#333333"
        assert t.body_color == "#333333"
        assert t.hint_color == "#999999"
        assert t.note_color == "#666666"
        assert t.divider_color == "#F5F5F5"

    def test_shape_density(self):
        t = A2UITheme()
        assert t.card_radius == "middle"
        assert t.card_width == 96
        assert t.card_padding == 16
        assert t.header_padding == 20
        assert t.section_gap == 12
        assert t.header_gap == 8
        assert t.kv_row_width == 98

    def test_root_surface_spacing(self):
        t = A2UITheme()
        assert t.root_padding == 2
        assert t.root_gap == 0


class TestA2UIThemeOverride:
    """P0: custom values override defaults, unspecified fields keep defaults."""

    def test_partial_override(self):
        t = A2UITheme(accent="#00FF00", root_gap=16)
        assert t.accent == "#00FF00"
        assert t.root_gap == 16
        assert t.page_bg == "#F5F5F5"  # unchanged

    def test_root_padding_list(self):
        t = A2UITheme(root_padding=[16, 32, 16, 16])
        assert t.root_padding == [16, 32, 16, 16]

    def test_full_dark_theme(self):
        dark = A2UITheme(
            accent="#4FC3F7",
            page_bg="#121212",
            card_bg="#1E1E1E",
            title_color="#EEEEEE",
            body_color="#CCCCCC",
            hint_color="#888888",
            divider_color="#333333",
        )
        assert dark.page_bg == "#121212"
        assert dark.card_bg == "#1E1E1E"


class TestA2UIThemeImmutability:
    """P0: frozen model prevents mutation."""

    def test_cannot_set_field(self):
        t = A2UITheme()
        with pytest.raises(ValidationError):
            t.accent = "#000000"

    def test_two_instances_independent(self):
        a = A2UITheme(accent="#AAA")
        b = A2UITheme(accent="#BBB")
        assert a.accent != b.accent


# ============ Backward-compat aliases ============


class TestBackwardCompatAliases:
    """P1: module-level constants in blocks.py match default theme values."""

    def test_aliases_match_defaults(self):
        t = A2UITheme()
        assert blocks_mod.ACCENT == t.accent
        assert blocks_mod.TITLE_COLOR == t.title_color
        assert blocks_mod.BODY_COLOR == t.body_color
        assert blocks_mod.HINT_COLOR == t.hint_color
        assert blocks_mod.NOTE_COLOR == t.note_color
        assert blocks_mod.CARD_BG == t.card_bg
        assert blocks_mod.PAGE_BG == t.page_bg
        assert blocks_mod.DIVIDER_COLOR == t.divider_color
        assert blocks_mod.CARD_RADIUS == t.card_radius


# ============ BlockComposer theme integration ============


class TestComposerTheme:
    """P0: BlockComposer.compose() applies theme to root Column."""

    def test_default_theme_applied(self):
        payload = BlockComposer().compose([], {})
        col = payload["components"][0]["component"]["Column"]
        assert col["backgroundColor"] == "#F5F5F5"
        assert col["padding"] == 2
        assert col["gap"] == 0

    def test_custom_theme_applied(self):
        theme = A2UITheme(page_bg="#000000", root_padding=10, root_gap=8)
        payload = BlockComposer().compose([], {}, theme=theme)
        col = payload["components"][0]["component"]["Column"]
        assert col["backgroundColor"] == "#000000"
        assert col["padding"] == 10
        assert col["gap"] == 8

    def test_protocol_constants_not_overridden_by_theme(self):
        payload = BlockComposer().compose([], {})
        col = payload["components"][0]["component"]["Column"]
        assert col["width"] == 100
        assert payload["style"] == "default"


# ============ RenderA2UITool._theme integration ============


class TestRenderA2UIToolTheme:
    """P0: _theme property resolves correctly."""

    def test_default_theme_when_no_blocks_config(self):
        tool = RenderA2UITool()
        assert tool._theme.page_bg == "#F5F5F5"

    def test_default_theme_when_blocks_has_no_theme(self):
        tool = RenderA2UITool(blocks=BlocksConfig())
        assert tool._theme.page_bg == "#F5F5F5"

    def test_custom_theme_from_blocks_config(self):
        custom = A2UITheme(page_bg="#222222", card_bg="#333333")
        tool = RenderA2UITool(blocks=BlocksConfig(theme=custom))
        assert tool._theme.page_bg == "#222222"
        assert tool._theme.card_bg == "#333333"


class TestHandleBlocksTheme:
    """P0: _handle_blocks root Column picks up theme values."""

    @pytest.fixture
    def themed_tool(self):
        from ark_agentic.agents.insurance.a2ui import INSURANCE_BLOCKS, INSURANCE_COMPONENTS
        return RenderA2UITool(
            blocks=BlocksConfig(
                agent_blocks=INSURANCE_BLOCKS,
                agent_components=INSURANCE_COMPONENTS,
                theme=A2UITheme(page_bg="#111111", root_gap=20, root_padding=[8, 8, 8, 8]),
            ),
            group="insurance",
            state_keys=("_rule_engine_result",),
        )

    @pytest.mark.asyncio
    async def test_root_column_uses_custom_theme(self, themed_tool):
        blocks = json.dumps([{"type": "Divider", "data": {}}])
        tc = ToolCall.create("render_a2ui", {"blocks": blocks})
        result = await themed_tool.execute(tc, context={"session_id": "s1"})
        assert not result.is_error
        root_col = result.content["components"][0]["component"]["Column"]
        assert root_col["backgroundColor"] == "#111111"
        assert root_col["gap"] == 20
        assert root_col["padding"] == [8, 8, 8, 8]


class TestExpandCardTheme:
    """P0: _expand_card uses theme for card styling."""

    @pytest.fixture
    def themed_card_tool(self):
        from ark_agentic.agents.insurance.a2ui import INSURANCE_BLOCKS, INSURANCE_COMPONENTS
        return RenderA2UITool(
            blocks=BlocksConfig(
                agent_blocks=INSURANCE_BLOCKS,
                agent_components=INSURANCE_COMPONENTS,
                theme=A2UITheme(
                    card_bg="#AAAAAA",
                    card_radius="large",
                    card_padding=24,
                    header_gap=16,
                ),
            ),
            group="insurance",
        )

    @pytest.mark.asyncio
    async def test_card_picks_up_theme_values(self, themed_card_tool):
        blocks = json.dumps([{
            "type": "Card",
            "data": {"children": [{"type": "Divider", "data": {}}]},
        }])
        tc = ToolCall.create("render_a2ui", {"blocks": blocks})
        result = await themed_card_tool.execute(tc, context={})
        assert not result.is_error

        card_comp = next(
            c for c in result.content["components"]
            if "Card" in c.get("component", {})
        )
        card = card_comp["component"]["Card"]
        assert card["backgroundColor"] == "#AAAAAA"
        assert card["borderRadius"] == "large"
        assert card["padding"] == 24

        col_comp = next(
            c for c in result.content["components"]
            if "Column" in c.get("component", {}) and c["id"].startswith("column-")
        )
        assert col_comp["component"]["Column"]["gap"] == 16

    @pytest.mark.asyncio
    async def test_card_data_overrides_theme_padding(self, themed_card_tool):
        blocks = json.dumps([{
            "type": "Card",
            "data": {
                "padding": 32,
                "gap": 4,
                "children": [{"type": "Divider", "data": {}}],
            },
        }])
        tc = ToolCall.create("render_a2ui", {"blocks": blocks})
        result = await themed_card_tool.execute(tc, context={})
        assert not result.is_error

        card_comp = next(
            c for c in result.content["components"]
            if "Card" in c.get("component", {})
        )
        assert card_comp["component"]["Card"]["padding"] == 32

        col_comp = next(
            c for c in result.content["components"]
            if "Column" in c.get("component", {}) and c["id"].startswith("column-")
        )
        assert col_comp["component"]["Column"]["gap"] == 4


# ============ Insurance INSURANCE_THEME ============


class TestInsuranceTheme:
    """P0: INSURANCE_THEME constant is correctly configured."""

    def test_insurance_theme_values(self):
        from ark_agentic.agents.insurance.tools import INSURANCE_THEME
        assert INSURANCE_THEME.root_gap == 16
        assert INSURANCE_THEME.root_padding == [16, 32, 16, 16]
        assert INSURANCE_THEME.section_gap == 12
        assert INSURANCE_THEME.header_gap == 8
        assert INSURANCE_THEME.card_padding == 16
        assert INSURANCE_THEME.page_bg == "#F5F5F5"  # inherits default


# ============ Leaf block theme via closure factory ============


class TestLeafBlockThemeFactory:
    """P0: create_insurance_blocks(theme) produces builders that use the given theme."""

    def test_section_header_uses_custom_accent(self):
        import itertools
        from ark_agentic.agents.insurance.a2ui.blocks import create_insurance_blocks

        custom = A2UITheme(accent="#00CCFF", title_color="#AABBCC", hint_color="#112233")
        blocks = create_insurance_blocks(custom)
        counter = itertools.count(1)
        id_gen = lambda prefix: f"{prefix.lower()}-{next(counter):03d}"

        comps = blocks["SectionHeader"]({"title": "Test", "tag": "T"}, id_gen)
        line_comp = next(c for c in comps if "Line" in c.get("component", {}))
        assert line_comp["component"]["Line"]["backgroundColor"] == "#00CCFF"

        text_comp = next(
            c for c in comps
            if "Text" in c.get("component", {})
            and c["component"]["Text"].get("bold") is True
        )
        assert text_comp["component"]["Text"]["color"] == "#AABBCC"

        tag_comp = next(c for c in comps if "Tag" in c.get("component", {}))
        assert tag_comp["component"]["Tag"]["color"] == "#112233"

    def test_kv_row_uses_custom_colors(self):
        import itertools
        from ark_agentic.agents.insurance.a2ui.blocks import create_insurance_blocks

        custom = A2UITheme(note_color="#AAAAAA", body_color="#BBBBBB")
        blocks = create_insurance_blocks(custom)
        counter = itertools.count(1)
        id_gen = lambda prefix: f"{prefix.lower()}-{next(counter):03d}"

        comps = blocks["KVRow"]({"label": "L", "value": "V"}, id_gen)
        texts = [c for c in comps if "Text" in c.get("component", {})]
        assert texts[0]["component"]["Text"]["color"] == "#AAAAAA"
        assert texts[1]["component"]["Text"]["color"] == "#BBBBBB"

    def test_divider_uses_custom_color(self):
        import itertools
        from ark_agentic.agents.insurance.a2ui.blocks import create_insurance_blocks

        custom = A2UITheme(divider_color="#DDDDDD")
        blocks = create_insurance_blocks(custom)
        counter = itertools.count(1)
        id_gen = lambda prefix: f"{prefix.lower()}-{next(counter):03d}"

        comps = blocks["Divider"]({}, id_gen)
        assert comps[0]["component"]["Divider"]["borderColor"] == "#DDDDDD"

    def test_accent_total_uses_custom_accent(self):
        import itertools
        from ark_agentic.agents.insurance.a2ui.blocks import create_insurance_blocks

        custom = A2UITheme(accent="#11FF11", title_color="#220022")
        blocks = create_insurance_blocks(custom)
        counter = itertools.count(1)
        id_gen = lambda prefix: f"{prefix.lower()}-{next(counter):03d}"

        comps = blocks["AccentTotal"]({"label": "Total", "value": "¥100"}, id_gen)
        texts = [c for c in comps if "Text" in c.get("component", {})]
        assert texts[0]["component"]["Text"]["color"] == "#220022"
        assert texts[1]["component"]["Text"]["color"] == "#11FF11"

    def test_default_factory_matches_original_constants(self):
        """Regression: default-theme factory output matches hardcoded defaults."""
        import itertools
        from ark_agentic.agents.insurance.a2ui.blocks import create_insurance_blocks

        blocks = create_insurance_blocks()
        counter = itertools.count(1)
        id_gen = lambda prefix: f"{prefix.lower()}-{next(counter):03d}"

        comps = blocks["SectionHeader"]({"title": "T"}, id_gen)
        line_comp = next(c for c in comps if "Line" in c.get("component", {}))
        assert line_comp["component"]["Line"]["backgroundColor"] == "#FF6600"

        counter2 = itertools.count(1)
        id_gen2 = lambda prefix: f"{prefix.lower()}-{next(counter2):03d}"
        div_comps = blocks["Divider"]({}, id_gen2)
        assert div_comps[0]["component"]["Divider"]["borderColor"] == "#F5F5F5"


class TestLeafComponentThemeFactory:
    """P0: create_insurance_components(theme) produces builders that use the given theme."""

    def test_summary_header_card_uses_custom_theme(self):
        import itertools
        from ark_agentic.agents.insurance.a2ui.components import create_insurance_components

        custom = A2UITheme(
            card_bg="#EEEEEE",
            card_radius="large",
            header_padding=24,
            accent="#00FF00",
            title_color="#111111",
        )
        components = create_insurance_components(custom)
        counter = itertools.count(1)
        id_gen = lambda prefix: f"{prefix.lower()}-{next(counter):03d}"

        raw_data: dict = {"options": []}
        output = components["WithdrawSummaryHeader"]({}, id_gen, raw_data)

        card_comp = next(
            c for c in output.components if "Card" in c.get("component", {})
        )
        assert card_comp["component"]["Card"]["backgroundColor"] == "#EEEEEE"
        assert card_comp["component"]["Card"]["borderRadius"] == "large"
        assert card_comp["component"]["Card"]["padding"] == 24

    def test_default_component_factory_matches_original(self):
        """Regression: default-theme component factory matches hardcoded defaults."""
        import itertools
        from ark_agentic.agents.insurance.a2ui.components import create_insurance_components

        components = create_insurance_components()
        counter = itertools.count(1)
        id_gen = lambda prefix: f"{prefix.lower()}-{next(counter):03d}"

        raw_data: dict = {"options": []}
        output = components["WithdrawSummaryHeader"]({}, id_gen, raw_data)

        card_comp = next(
            c for c in output.components if "Card" in c.get("component", {})
        )
        assert card_comp["component"]["Card"]["backgroundColor"] == "#FFFFFF"
        assert card_comp["component"]["Card"]["borderRadius"] == "middle"
        assert card_comp["component"]["Card"]["padding"] == 20
