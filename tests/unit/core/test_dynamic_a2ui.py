"""Tests for Dynamic A2UI: transforms, flattener, render_a2ui tool, and mode switching."""

import json

import pytest

from ark_agentic.core.a2ui.transforms import (
    execute_transforms,
    _resolve_path,
    _eval_condition,
)
from ark_agentic.core.a2ui.flattener import TreeFlattener, _resolve_binding
from ark_agentic.core.tools.render_a2ui import BlocksConfig, RenderA2UITool
from ark_agentic.core.types import RunOptions, ToolCall


# ============ Transform DSL ============


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


class TestTransforms:
    def test_get_simple(self):
        result, warns = execute_transforms(
            {"val": {"get": "requested_amount"}},
            _SAMPLE_DATA,
        )
        assert result["val"] == 50000
        assert not warns

    def test_get_with_currency_format(self):
        result, _ = execute_transforms(
            {"val": {"get": "requested_amount", "format": "currency"}},
            _SAMPLE_DATA,
        )
        assert result["val"] == "¥ 50,000.00"

    def test_get_with_percent_format(self):
        result, _ = execute_transforms(
            {"val": {"get": "options", "format": "raw"}},
            {"options": 0.05},
        )
        result2, _ = execute_transforms(
            {"rate": {"get": "rate", "format": "percent"}},
            {"rate": 0.05},
        )
        assert result2["rate"] == "5%"

    def test_literal(self):
        result, _ = execute_transforms({"label": {"literal": "Hello"}}, {})
        assert result["label"] == "Hello"

    def test_sum_single_field(self):
        result, _ = execute_transforms(
            {"total": {"sum": "options.survival_fund_amt", "format": "currency"}},
            _SAMPLE_DATA,
        )
        assert result["total"] == "¥ 12,000.00"

    def test_sum_multiple_fields(self):
        result, _ = execute_transforms(
            {"total": {"sum": ["options.survival_fund_amt", "options.bonus_amt"], "format": "currency"}},
            _SAMPLE_DATA,
        )
        assert result["total"] == "¥ 17,200.00"

    def test_sum_with_where(self):
        result, _ = execute_transforms(
            {"total": {"sum": "options.loan_amt", "where": {"loan_amt": "> 0"}, "format": "currency"}},
            _SAMPLE_DATA,
        )
        assert result["total"] == "¥ 33,600.00"

    def test_count(self):
        result, _ = execute_transforms(
            {"n": {"count": "options", "where": {"loan_amt": "> 0"}}},
            _SAMPLE_DATA,
        )
        assert result["n"] == 1

    def test_concat(self):
        result, _ = execute_transforms(
            {"msg": {"concat": ["金额：", {"get": "requested_amount", "format": "currency"}]}},
            _SAMPLE_DATA,
        )
        assert result["msg"] == "金额：¥ 50,000.00"

    def test_select_with_map(self):
        result, _ = execute_transforms(
            {
                "items": {
                    "select": "options",
                    "where": {"survival_fund_amt": "> 0"},
                    "map": {
                        "name": "$.product_name",
                        "amt": {"get": "$.survival_fund_amt", "format": "currency"},
                    },
                }
            },
            _SAMPLE_DATA,
        )
        assert len(result["items"]) == 1
        assert result["items"][0]["name"] == "金瑞人生年金险"

    def test_missing_field_with_default(self):
        result, _ = execute_transforms(
            {"val": {"get": "nonexistent", "default": 0, "format": "int"}},
            _SAMPLE_DATA,
        )
        assert result["val"] == "0"

    def test_missing_field_without_default_warns(self):
        result, warns = execute_transforms(
            {"val": {"get": "nonexistent"}},
            _SAMPLE_DATA,
        )
        assert "val" not in result
        assert any("TRANSFORM_WARN" in w for w in warns)

    def test_or_condition(self):
        assert _eval_condition(
            {"survival_fund_amt": 12000, "bonus_amt": 0},
            {"or": [{"survival_fund_amt": "> 0"}, {"bonus_amt": "> 0"}]},
        )
        assert not _eval_condition(
            {"survival_fund_amt": 0, "bonus_amt": 0},
            {"or": [{"survival_fund_amt": "> 0"}, {"bonus_amt": "> 0"}]},
        )

    def test_resolve_path_dot_notation(self):
        data = {"a": {"b": {"c": 42}}}
        assert _resolve_path(data, "a.b.c") == 42

    def test_resolve_path_array_wildcard(self):
        data = {"items": [{"x": 1}, {"x": 2}]}
        assert _resolve_path(data, "items.x") == [1, 2]


# ============ TreeFlattener ============


class TestFlattener:
    def test_simple_text(self):
        tree = {"Text": {"text": "$hello", "usageHint": "title"}}
        flattener = TreeFlattener()
        payload = flattener.flatten(tree, {"hello": "world"})
        assert payload["event"] == "beginRendering"
        assert len(payload["components"]) == 1
        comp = payload["components"][0]
        assert "Text" in comp["component"]
        text_props = comp["component"]["Text"]
        assert text_props["text"] == {"path": "hello"}
        assert text_props["usageHint"] == "title"

    def test_literal_text(self):
        tree = {"Text": {"text": "static text"}}
        flattener = TreeFlattener()
        payload = flattener.flatten(tree, {})
        text_props = payload["components"][0]["component"]["Text"]
        assert text_props["text"] == {"literalString": "static text"}

    def test_column_with_children(self):
        tree = {"Column": {"gap": 8, "children": [
            {"Text": {"text": "$a"}},
            {"Text": {"text": "$b"}},
        ]}}
        flattener = TreeFlattener()
        payload = flattener.flatten(tree, {"a": "1", "b": "2"})
        assert len(payload["components"]) == 3
        col_comp = payload["components"][-1]["component"]["Column"]
        assert "children" in col_comp
        child_ids = col_comp["children"]["explicitList"]
        assert len(child_ids) == 2

    def test_button_with_action(self):
        tree = {"Button": {"text": "Click", "action": {"name": "query", "args": "$q"}}}
        flattener = TreeFlattener()
        payload = flattener.flatten(tree, {"q": "hello"})
        btn = payload["components"][0]["component"]["Button"]
        assert btn["action"]["name"] == "query"
        assert btn["action"]["args"] == {"path": "q"}

    def test_standard_props_passthrough(self):
        tree = {"Card": {"width": 96, "backgroundColor": "#FFF", "borderRadius": "middle", "children": []}}
        flattener = TreeFlattener()
        payload = flattener.flatten(tree, {})
        card = payload["components"][0]["component"]["Card"]
        assert card["width"] == 96
        assert card["backgroundColor"] == "#FFF"
        assert card["borderRadius"] == "middle"

    def test_deprecated_shorthand_props(self):
        """Tolerance layer: old shorthand props are accepted with warnings."""
        tree = {"Card": {"w": 96, "bg": "#FFF", "radius": "middle", "children": []}}
        flattener = TreeFlattener()
        payload = flattener.flatten(tree, {})
        card = payload["components"][0]["component"]["Card"]
        assert card["width"] == 96
        assert card["backgroundColor"] == "#FFF"
        assert card["borderRadius"] == "middle"
        assert any("DEPRECATED" in w for w in flattener.warnings)

    def test_deprecated_lowercase_types(self):
        """Tolerance layer: old lowercase types are accepted with warnings."""
        tree = {"column": {"gap": 8, "children": [{"text": {"text": "$a"}}]}}
        flattener = TreeFlattener()
        payload = flattener.flatten(tree, {"a": "1"})
        assert any(c for c in payload["components"] if "Column" in c["component"])
        assert any(c for c in payload["components"] if "Text" in c["component"])
        assert any("DEPRECATED" in w for w in flattener.warnings)

    def test_deprecated_field_prop(self):
        """Tolerance layer: old 'field' prop is accepted."""
        tree = {"Text": {"field": "$hello"}}
        flattener = TreeFlattener()
        payload = flattener.flatten(tree, {})
        text_props = payload["components"][0]["component"]["Text"]
        assert text_props["text"] == {"path": "hello"}
        assert any("DEPRECATED" in w and "field" in w for w in flattener.warnings)

    def test_deprecated_style_prop(self):
        """Tolerance layer: old 'style' prop is expanded."""
        tree = {"Text": {"text": "$hello", "style": "title"}}
        flattener = TreeFlattener()
        payload = flattener.flatten(tree, {})
        text_props = payload["components"][0]["component"]["Text"]
        assert text_props["usageHint"] == "title"
        assert any("DEPRECATED" in w and "style" in w for w in flattener.warnings)

    def test_popup_defaults(self):
        tree = {"Popup": {"children": [{"Text": {"text": "hi"}}]}}
        flattener = TreeFlattener()
        payload = flattener.flatten(tree, {})
        popup = next(
            c for c in payload["components"]
            if "Popup" in c["component"]
        )["component"]["Popup"]
        assert popup["modelValue"] is False
        assert popup["overlay"] is True

    def test_list_component(self):
        tree = {"List": {"direction": "vertical", "gap": 10, "dataSource": "$items",
                         "child": {"Text": {"text": "$item.label"}}}}
        flattener = TreeFlattener()
        payload = flattener.flatten(tree, {"items": []})
        list_comp = next(
            c for c in payload["components"]
            if "List" in c["component"]
        )["component"]["List"]
        assert list_comp["dataSource"] == {"path": "items"}
        assert list_comp["direction"] == "vertical"

    def test_auto_id_generation(self):
        tree = {"Column": {"children": [
            {"Text": {"text": "a"}},
            {"Text": {"text": "b"}},
        ]}}
        flattener = TreeFlattener()
        payload = flattener.flatten(tree, {})
        ids = [c["id"] for c in payload["components"]]
        assert len(set(ids)) == 3

    def test_surface_id_auto_generated(self):
        tree = {"Text": {"text": "x"}}
        flattener = TreeFlattener()
        payload = flattener.flatten(tree, {})
        assert payload["surfaceId"].startswith("dyn-")

    def test_explicit_surface_id(self):
        tree = {"Text": {"text": "x"}}
        flattener = TreeFlattener()
        payload = flattener.flatten(tree, {}, surface_id="my-surface")
        assert payload["surfaceId"] == "my-surface"

    def test_unknown_type_raises(self):
        tree = {"UnknownWidget": {"text": "x"}}
        flattener = TreeFlattener()
        with pytest.raises(ValueError, match="Unknown component type"):
            flattener.flatten(tree, {})

    def test_resolve_binding_dollar(self):
        assert _resolve_binding("$foo") == {"path": "foo"}

    def test_resolve_binding_string(self):
        assert _resolve_binding("hello") == {"literalString": "hello"}

    def test_resolve_binding_passthrough(self):
        val = {"path": "existing"}
        assert _resolve_binding(val) == {"path": "existing"}

    def test_resolve_binding_dict_to_literal(self):
        val = {"url": "https://example.com"}
        assert _resolve_binding(val) == {"literalString": {"url": "https://example.com"}}


# ============ Soft Validation ============


class TestSoftValidation:
    def test_detects_hardcoded_currency_in_text(self):
        payload = {
            "components": [{
                "id": "text-001",
                "component": {"Text": {"text": {"literalString": "¥ 50,000.00"}}}
            }],
            "data": {},
        }
        warnings = TreeFlattener.soft_validate(payload)
        assert any("SOFT_WARN" in w and "text-001" in w for w in warnings)

    def test_no_warning_for_field_reference(self):
        payload = {
            "components": [{
                "id": "text-001",
                "component": {"Text": {"text": {"path": "amount"}}}
            }],
            "data": {"amount": "¥ 50,000.00"},
        }
        warnings = TreeFlattener.soft_validate(payload, transform_keys={"amount"})
        assert not warnings

    def test_detects_suspicious_data_not_from_transforms(self):
        payload = {
            "components": [],
            "data": {"val": "¥ 10,000 元"},
        }
        warnings = TreeFlattener.soft_validate(payload, transform_keys=set())
        assert any("SOFT_WARN" in w for w in warnings)


# ============ RenderA2UITool (blocks path) ============


class TestRenderA2UITool:
    @pytest.fixture
    def tool(self):
        from ark_agentic.agents.insurance.a2ui import INSURANCE_BLOCKS, INSURANCE_COMPONENTS
        return RenderA2UITool(
            blocks=BlocksConfig(
                agent_blocks=INSURANCE_BLOCKS,
                agent_components=INSURANCE_COMPONENTS,
                root_gap=16,
                root_padding=[16, 32, 16, 16],
            ),
            group="insurance",
        )

    @pytest.fixture
    def ctx(self):
        return {
            "_rule_engine_result": _SAMPLE_DATA,
            "session_id": "test-session-123",
        }

    @pytest.mark.asyncio
    async def test_basic_render(self, tool, ctx):
        blocks = json.dumps([
            {"type": "Card", "data": {"children": [
                {"type": "KVRow", "data": {
                    "label": "Total",
                    "value": {"get": "total_available_incl_loan", "format": "currency"},
                }},
            ]}},
        ])
        tc = ToolCall.create("render_a2ui", {"blocks": blocks})
        result = await tool.execute(tc, context=ctx)
        assert not result.is_error
        assert result.content["event"] == "beginRendering"

    @pytest.mark.asyncio
    async def test_invalid_blocks_json(self, tool, ctx):
        tc = ToolCall.create("render_a2ui", {"blocks": "not json"})
        result = await tool.execute(tc, context=ctx)
        assert result.is_error
        assert "JSON" in result.content

    @pytest.mark.asyncio
    async def test_invalid_blocks_not_array(self, tool, ctx):
        tc = ToolCall.create("render_a2ui", {"blocks": '{"x":1}'})
        result = await tool.execute(tc, context=ctx)
        assert result.is_error

    @pytest.mark.asyncio
    async def test_no_transforms(self, tool, ctx):
        blocks = json.dumps([{"type": "Divider", "data": {}}])
        tc = ToolCall.create("render_a2ui", {"blocks": blocks})
        result = await tool.execute(tc, context=ctx)
        assert not result.is_error

    @pytest.mark.asyncio
    async def test_unknown_block_type_error(self, tool, ctx):
        blocks = json.dumps([{"type": "FakeBlock", "data": {}}])
        tc = ToolCall.create("render_a2ui", {"blocks": blocks})
        result = await tool.execute(tc, context=ctx)
        assert result.is_error


# ============ Policy List Golden E2E ============


class TestPolicyListGoldenE2E:
    """End-to-end test using A2UI-native format from the updated SKILL.md."""

    POLICY_LIST_TRANSFORMS = {
        "list_title": {"literal": "您的保单概览"},
        "policy_count": {"concat": ["共 ", {"count": "options"}, " 张保单"]},
        "total_value": {
            "concat": [
                "总可用金额：",
                {"get": "total_available_incl_loan", "format": "currency"},
            ]
        },
        "policy_list": {
            "select": "options",
            "map": {
                "name": "$.product_name",
                "type_display": {
                    "switch": "$.product_type",
                    "cases": {
                        "whole_life": "终身寿险",
                        "annuity": "年金险",
                        "universal_life": "万能险",
                    },
                    "default": "保险",
                },
                "total": {"get": "$.available_amount", "format": "currency"},
                "survival": {"get": "$.survival_fund_amt", "format": "currency"},
                "bonus": {"get": "$.bonus_amt", "format": "currency"},
                "loan": {"get": "$.loan_amt", "format": "currency"},
            },
        },
    }

    POLICY_LIST_TREE = {
        "Column": {
            "backgroundColor": "#F5F5F5",
            "padding": 2,
            "gap": 0,
            "children": [
                {
                    "Card": {
                        "backgroundColor": "#FFFFFF",
                        "width": 96,
                        "borderRadius": "middle",
                        "padding": 20,
                        "children": [
                            {
                                "Column": {
                                    "alignment": "center",
                                    "gap": 8,
                                    "children": [
                                        {"Text": {"text": "$list_title", "usageHint": "title"}},
                                        {"Text": {"text": "$policy_count", "usageHint": "tips", "size": "small"}},
                                        {"Text": {"text": "$total_value", "color": "#FF6600", "bold": True, "size": "xxlarge"}},
                                    ],
                                }
                            }
                        ],
                    }
                },
                {
                    "Card": {
                        "backgroundColor": "#FFFFFF",
                        "width": 96,
                        "borderRadius": "middle",
                        "padding": 16,
                        "children": [
                            {
                                "List": {
                                    "direction": "vertical",
                                    "gap": 12,
                                    "dataSource": "$policy_list",
                                    "child": {
                                        "Column": {
                                            "gap": 6,
                                            "padding": 12,
                                            "backgroundColor": "#FAFAFA",
                                            "borderRadius": "small",
                                            "children": [
                                                {
                                                    "Row": {
                                                        "distribution": "spaceBetween",
                                                        "alignment": "middle",
                                                        "children": [
                                                            {"Text": {"text": "$item.name", "usageHint": "title"}},
                                                            {"Tag": {"text": "$item.type_display", "size": "small"}},
                                                        ],
                                                    }
                                                },
                                                {
                                                    "Row": {
                                                        "distribution": "spaceBetween",
                                                        "children": [
                                                            {"Text": {"text": "$item.total", "color": "#FF6600", "bold": True, "size": "large"}},
                                                            {"Text": {"text": "$item.survival", "usageHint": "tips", "size": "small"}},
                                                        ],
                                                    }
                                                },
                                            ],
                                        }
                                    },
                                    "emptyChild": {"Text": {"text": "暂无保单", "usageHint": "tips"}},
                                }
                            }
                        ],
                    }
                },
            ],
        }
    }

    def test_transforms_produce_correct_data(self):
        computed, warnings = execute_transforms(self.POLICY_LIST_TRANSFORMS, _SAMPLE_DATA)
        assert not warnings, f"Unexpected warnings: {warnings}"

        assert computed["list_title"] == "您的保单概览"
        assert computed["policy_count"] == "共 2 张保单"
        assert "252,800" in computed["total_value"]

        policy_list = computed["policy_list"]
        assert isinstance(policy_list, list)
        assert len(policy_list) == 2

        for item in policy_list:
            assert item["name"] is not None and item["name"] != ""
            assert item["type_display"] is not None and item["type_display"] != ""
            assert item["total"] is not None and item["total"] != ""

        assert policy_list[0]["name"] == "平安福终身寿险"
        assert policy_list[0]["type_display"] == "终身寿险"
        assert policy_list[1]["type_display"] == "年金险"

    def test_flatten_produces_valid_payload(self):
        computed, _ = execute_transforms(self.POLICY_LIST_TRANSFORMS, _SAMPLE_DATA)

        flattener = TreeFlattener()
        payload = flattener.flatten(
            self.POLICY_LIST_TREE,
            computed,
            surface_id="test-policy-list",
        )

        assert payload["event"] == "beginRendering"
        assert payload["surfaceId"] == "test-policy-list"
        assert payload["rootComponentId"] is not None

        comp_map = {c["id"]: c["component"] for c in payload["components"]}
        assert payload["rootComponentId"] in comp_map

        list_comps = [
            c for c in payload["components"]
            if "List" in c["component"]
        ]
        assert len(list_comps) == 1
        list_props = list_comps[0]["component"]["List"]
        assert list_props["dataSource"] == {"path": "policy_list"}
        assert "child" in list_props

        child_id = list_props["child"]
        assert child_id in comp_map

    def test_validator_passes(self):
        from ark_agentic.core.a2ui.validator import validate_payload
        from ark_agentic.core.a2ui.contract_models import validate_event_payload

        computed, _ = execute_transforms(self.POLICY_LIST_TRANSFORMS, _SAMPLE_DATA)
        flattener = TreeFlattener()
        payload = flattener.flatten(
            self.POLICY_LIST_TREE,
            computed,
            surface_id="test-policy-list",
        )

        validate_event_payload(payload)

        result = validate_payload(payload)
        assert result.ok, f"Validation failed: {result.errors}"

    def test_soft_validate_no_hardcoded_amounts(self):
        computed, _ = execute_transforms(self.POLICY_LIST_TRANSFORMS, _SAMPLE_DATA)
        flattener = TreeFlattener()
        payload = flattener.flatten(
            self.POLICY_LIST_TREE,
            computed,
            surface_id="test-policy-list",
        )
        warnings = TreeFlattener.soft_validate(payload, transform_keys=set(computed.keys()))
        assert not warnings, f"Soft validation warnings: {warnings}"


# ============ Flat Format Tolerance ============


class TestFlatFormatTolerance:
    """Tests for flat-format node handling in flattener (deprecated path)."""

    def test_flat_to_standard(self):
        from ark_agentic.core.a2ui.flattener import _normalize_flat_format
        flat = {"type": "Column", "children": [{"type": "Text", "props": {"text": "$x"}}]}
        result = _normalize_flat_format(flat)
        assert "Column" in result
        child = result["Column"]["children"][0]
        assert "Text" in child

    def test_flat_format_flattener_direct(self):
        """Flattener handles flat-format nodes directly."""
        flat_tree = {
            "type": "Column",
            "children": [{"type": "Text", "props": {"text": "$val"}}]
        }
        data = {"val": "hello"}
        flattener = TreeFlattener()
        payload = flattener.flatten(flat_tree, data, surface_id="test")
        assert payload["event"] == "beginRendering"

    def test_type_alias_badge_flattener_direct(self):
        """Flattener normalizes 'badge' -> Tag."""
        tree = {
            "type": "Column",
            "children": [{"type": "badge", "props": {"text": "$status"}}]
        }
        data = {"status": "有效"}
        flattener = TreeFlattener()
        payload = flattener.flatten(tree, data, surface_id="test")
        tag_comps = [c for c in payload["components"] if "Tag" in c["component"]]
        assert len(tag_comps) == 1


# ============ Widget Tree Validation (deprecated, tested via flattener) ============


class TestStrictValidationMode:
    @pytest.fixture
    def tool(self):
        from ark_agentic.agents.insurance.a2ui import INSURANCE_BLOCKS, INSURANCE_COMPONENTS
        return RenderA2UITool(
            blocks=BlocksConfig(
                agent_blocks=INSURANCE_BLOCKS,
                agent_components=INSURANCE_COMPONENTS,
            ),
            group="insurance",
        )

    @pytest.fixture
    def ctx(self):
        return {"session_id": "test-session-123"}

    @pytest.mark.asyncio
    async def test_enforce_mode_returns_error(self, tool, ctx, monkeypatch):
        monkeypatch.setenv("A2UI_STRICT_VALIDATION", "enforce")
        blocks = json.dumps([{"type": "Divider", "data": {}}])
        tc = ToolCall.create("render_a2ui", {"blocks": blocks})

        from unittest.mock import patch
        with patch("ark_agentic.core.a2ui.guard.validate_event_payload", side_effect=ValueError("Mocked contract error")):
            result = await tool.execute(tc, context=ctx)
            assert result.is_error is True
            assert "A2UI contract invalid: [EVENT_CONTRACT] Mocked contract error" in result.content

    @pytest.mark.asyncio
    async def test_warn_mode_returns_a2ui_result(self, tool, ctx, monkeypatch):
        monkeypatch.setenv("A2UI_STRICT_VALIDATION", "warn")
        blocks = json.dumps([{"type": "Divider", "data": {}}])
        tc = ToolCall.create("render_a2ui", {"blocks": blocks})

        from unittest.mock import patch
        with patch("ark_agentic.core.a2ui.guard.validate_event_payload", side_effect=ValueError("Mocked contract error")):
            result = await tool.execute(tc, context=ctx)
            assert result.is_error is False
            assert result.content["event"] == "beginRendering"
            assert "warnings" in result.metadata
            assert any("Mocked contract error" in w for w in result.metadata["warnings"])
            assert result.metadata["a2ui_validation"]["mode"] == "warn"
