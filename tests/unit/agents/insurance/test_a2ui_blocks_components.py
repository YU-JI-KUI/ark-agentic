"""Tests for insurance A2UI blocks, components, and the agent pipeline."""

import json

import pytest

from ark_agentic.agents.insurance.a2ui.blocks import (
    INSURANCE_BLOCKS,
    build_section_header,
    build_kv_row,
    build_accent_total,
    build_hint_text,
    build_action_button,
    build_divider,
)
from ark_agentic.agents.insurance.a2ui.components import (
    INSURANCE_COMPONENTS,
    build_withdraw_summary_header,
    build_withdraw_summary_section,
    build_withdraw_plan_card,
)
from ark_agentic.core.tools.render_a2ui import BlocksConfig, RenderA2UITool
from ark_agentic.core.types import ToolCall


_SAMPLE_RAW_DATA = {
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
            "refund_amt": 42000,
            "refund_fee_rate": 0.0,
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
            "refund_amt": 160000,
            "refund_fee_rate": 0.01,
        },
    ],
}


def _id_gen():
    counter = [0]
    def gen(prefix: str) -> str:
        counter[0] += 1
        return f"{prefix.lower()}-{counter[0]:03d}"
    return gen


# ============ Insurance Blocks ============


class TestInsuranceBlocksRegistry:
    def test_all_blocks_registered(self):
        expected = {"SectionHeader", "KVRow", "AccentTotal", "HintText", "ActionButton", "Divider"}
        assert set(INSURANCE_BLOCKS.keys()) == expected


class TestSectionHeaderBlock:
    def test_basic(self):
        comps = build_section_header({"title": "Test"}, _id_gen())
        assert len(comps) >= 3
        row = comps[0]
        assert "Row" in row["component"]
        line_comps = [c for c in comps if "Line" in c.get("component", {})]
        assert len(line_comps) == 1
        assert line_comps[0]["component"]["Line"]["backgroundColor"] == "#FF6600"

    def test_with_tag(self):
        comps = build_section_header(
            {"title": "T", "tag": "不影响保障", "tag_color": "#6cb585"}, _id_gen()
        )
        tag_comps = [c for c in comps if "Tag" in c.get("component", {})]
        assert len(tag_comps) == 1
        assert tag_comps[0]["component"]["Tag"]["color"] == "#6cb585"


class TestKVRowBlock:
    def test_basic(self):
        comps = build_kv_row({"label": "生存金", "value": "¥ 12,000"}, _id_gen())
        assert len(comps) == 3
        row = comps[0]
        assert row["component"]["Row"]["distribution"] == "spaceBetween"

    def test_custom_colors(self):
        comps = build_kv_row(
            {"label": "L", "value": "V", "label_color": "#333", "value_color": "#F00", "bold": True},
            _id_gen(),
        )
        label_text = comps[1]["component"]["Text"]
        assert label_text["color"] == "#333"
        assert label_text["bold"] is True


class TestAccentTotalBlock:
    def test_with_label(self):
        comps = build_accent_total({"label": "合计可用", "value": "¥ 15,500"}, _id_gen())
        assert len(comps) == 3
        assert "Row" in comps[0]["component"]

    def test_without_label(self):
        comps = build_accent_total({"value": "¥ 15,500"}, _id_gen())
        assert len(comps) == 1
        text = comps[0]["component"]["Text"]
        assert text["color"] == "#FF6600"
        assert text["fontSize"] == "16px"


class TestActionButtonBlock:
    def test_primary(self):
        comps = build_action_button(
            {"text": "领取", "action": {"name": "query", "args": {"queryMsg": "go"}}},
            _id_gen(),
        )
        assert len(comps) == 1
        btn = comps[0]["component"]["Button"]
        assert btn["type"] == "primary"
        assert btn["size"] == "small"
        assert btn["width"] == 100


# ============ Insurance Components ============


class TestInsuranceComponentsRegistry:
    def test_all_components_registered(self):
        expected = {"WithdrawSummaryHeader", "WithdrawSummarySection", "WithdrawPlanCard"}
        assert set(INSURANCE_COMPONENTS.keys()) == expected


class TestWithdrawSummaryHeader:
    def test_basic(self):
        output = build_withdraw_summary_header(
            {"sections": ["zero_cost", "loan"]},
            _id_gen(),
            _SAMPLE_RAW_DATA,
        )
        assert len(output.components) >= 4
        card = output.components[0]
        assert "Card" in card["component"]
        assert card["component"]["Card"]["padding"] == 20


class TestWithdrawSummarySection:
    def test_zero_cost(self):
        output = build_withdraw_summary_section(
            {"section": "zero_cost"},
            _id_gen(),
            _SAMPLE_RAW_DATA,
        )
        assert len(output.components) > 0
        card = output.components[0]
        assert "Card" in card["component"]

    def test_loan(self):
        output = build_withdraw_summary_section(
            {"section": "loan"},
            _id_gen(),
            _SAMPLE_RAW_DATA,
        )
        assert len(output.components) > 0

    def test_partial_surrender_total_color_is_gray(self):
        raw = {
            "options": [
                {"policy_id": "P1", "product_name": "X", "product_type": "whole_life",
                 "survival_fund_amt": 0, "bonus_amt": 0, "loan_amt": 0, "refund_amt": 5000},
            ]
        }
        output = build_withdraw_summary_section(
            {"section": "partial_surrender"}, _id_gen(), raw,
        )
        total_texts = [c for c in output.components if "Text" in c.get("component", {})
                       and c["component"]["Text"].get("bold") is True
                       and "合计" in str(c["component"]["Text"].get("text", {}).get("literalString", ""))]
        assert len(total_texts) == 1
        assert total_texts[0]["component"]["Text"]["color"] == "#999999"

    def test_zero_cost_total_color_is_accent(self):
        output = build_withdraw_summary_section(
            {"section": "zero_cost"}, _id_gen(), _SAMPLE_RAW_DATA,
        )
        total_texts = [c for c in output.components if "Text" in c.get("component", {})
                       and c["component"]["Text"].get("bold") is True
                       and "合计" in str(c["component"]["Text"].get("text", {}).get("literalString", ""))]
        assert len(total_texts) == 1
        assert total_texts[0]["component"]["Text"]["color"] == "#FF6600"

    def test_empty_section_returns_empty(self):
        data_no_loan = {
            "options": [
                {"policy_id": "P1", "product_name": "X", "product_type": "annuity",
                 "survival_fund_amt": 100, "bonus_amt": 0, "loan_amt": 0, "refund_amt": 0},
            ]
        }
        output = build_withdraw_summary_section(
            {"section": "loan"},
            _id_gen(),
            data_no_loan,
        )
        assert output.components == []


class TestWithdrawPlanCard:
    def test_basic(self):
        output = build_withdraw_plan_card(
            {"channels": ["survival_fund", "bonus"], "target": 10000, "title": "零成本"},
            _id_gen(),
            _SAMPLE_RAW_DATA,
        )
        assert len(output.components) > 0
        card = output.components[0]
        assert "Card" in card["component"]
        assert output.llm_digest
        assert "channels" in output.llm_digest
        assert output.state_delta is not None
        assert "_plan_allocations" in output.state_delta

    def test_tag_color_default_green(self):
        output = build_withdraw_plan_card(
            {"channels": ["survival_fund"], "target": 5000, "title": "T", "tag": "(ok)"},
            _id_gen(), _SAMPLE_RAW_DATA,
        )
        tag_texts = [c for c in output.components if "Text" in c.get("component", {})
                     and "(ok)" in str(c["component"]["Text"].get("text", {}).get("literalString", ""))]
        assert len(tag_texts) == 1
        assert tag_texts[0]["component"]["Text"]["color"] == "#52C41A"

    def test_tag_color_custom(self):
        output = build_withdraw_plan_card(
            {"channels": ["policy_loan"], "target": 5000, "title": "T",
             "tag": "(利息)", "tag_color": "#FA8C16"},
            _id_gen(), _SAMPLE_RAW_DATA,
        )
        tag_texts = [c for c in output.components if "Text" in c.get("component", {})
                     and "(利息)" in str(c["component"]["Text"].get("text", {}).get("literalString", ""))]
        assert len(tag_texts) == 1
        assert tag_texts[0]["component"]["Text"]["color"] == "#FA8C16"

    def test_button_variant_default_primary(self):
        output = build_withdraw_plan_card(
            {"channels": ["survival_fund"], "target": 5000, "title": "T"},
            _id_gen(), _SAMPLE_RAW_DATA,
        )
        buttons = [c for c in output.components if "Button" in c.get("component", {})]
        for btn in buttons:
            assert btn["component"]["Button"]["type"] == "primary"

    def test_button_variant_secondary(self):
        output = build_withdraw_plan_card(
            {"channels": ["policy_loan"], "target": 5000, "title": "T",
             "button_variant": "secondary"},
            _id_gen(), _SAMPLE_RAW_DATA,
        )
        buttons = [c for c in output.components if "Button" in c.get("component", {})]
        assert len(buttons) > 0, "Expected at least one button"
        for btn in buttons:
            assert btn["component"]["Button"]["type"] == "secondary"


# ============ Agent Pipeline (Card expansion) ============


class TestAgentPipeline:
    @pytest.fixture
    def tool(self):
        return RenderA2UITool(
            blocks=BlocksConfig(
                agent_blocks=INSURANCE_BLOCKS,
                agent_components=INSURANCE_COMPONENTS,
                root_gap=16,
                root_padding=[16, 32, 16, 16],
            ),
            group="insurance",
            state_keys=("_rule_engine_result",),
        )

    @pytest.fixture
    def ctx(self):
        return {
            "_rule_engine_result": _SAMPLE_RAW_DATA,
            "session_id": "test-session",
        }

    @pytest.mark.asyncio
    async def test_card_expansion(self, tool, ctx):
        blocks = json.dumps([
            {"type": "Card", "data": {"children": [
                {"type": "SectionHeader", "data": {"title": "保单A"}},
                {"type": "KVRow", "data": {"label": "生存金", "value": "¥ 12,000"}},
                {"type": "Divider"},
                {"type": "AccentTotal", "data": {"label": "合计", "value": "¥ 12,000"}},
            ]}},
        ])
        tc = ToolCall.create("render_a2ui", {"blocks": blocks})
        result = await tool.execute(tc, context=ctx)
        assert not result.is_error
        payload = result.content
        assert payload["event"] == "beginRendering"
        root = payload["components"][0]
        assert "Column" in root["component"]
        assert root["component"]["Column"]["gap"] == 16
        assert root["component"]["Column"]["padding"] == [16, 32, 16, 16]
        card_comps = [c for c in payload["components"] if "Card" in c.get("component", {})]
        assert len(card_comps) == 1

    @pytest.mark.asyncio
    async def test_nested_card_expansion(self, tool, ctx):
        blocks = json.dumps([
            {"type": "Card", "data": {"children": [
                {"type": "Card", "data": {"children": [
                    {"type": "KVRow", "data": {"label": "A", "value": "B"}},
                ]}},
            ]}},
        ])
        tc = ToolCall.create("render_a2ui", {"blocks": blocks})
        result = await tool.execute(tc, context=ctx)
        assert not result.is_error
        card_comps = [c for c in result.content["components"] if "Card" in c.get("component", {})]
        assert len(card_comps) == 2

    @pytest.mark.asyncio
    async def test_card_max_depth_exceeded(self, tool, ctx):
        blocks = json.dumps([
            {"type": "Card", "data": {"children": [
                {"type": "Card", "data": {"children": [
                    {"type": "Card", "data": {"children": [
                        {"type": "Card", "data": {"children": [
                            {"type": "KVRow", "data": {"label": "A", "value": "B"}},
                        ]}},
                    ]}},
                ]}},
            ]}},
        ])
        tc = ToolCall.create("render_a2ui", {"blocks": blocks})
        result = await tool.execute(tc, context=ctx)
        assert result.is_error
        assert "嵌套" in result.content

    @pytest.mark.asyncio
    async def test_component_in_pipeline(self, tool, ctx):
        blocks = json.dumps([
            {"type": "WithdrawSummaryHeader", "data": {"sections": ["zero_cost"]}},
            {"type": "WithdrawSummarySection", "data": {"section": "zero_cost"}},
        ])
        tc = ToolCall.create("render_a2ui", {"blocks": blocks})
        result = await tool.execute(tc, context=ctx)
        assert not result.is_error
        card_comps = [c for c in result.content["components"] if "Card" in c.get("component", {})]
        assert len(card_comps) >= 2

    @pytest.mark.asyncio
    async def test_mixed_blocks_and_components(self, tool, ctx):
        blocks = json.dumps([
            {"type": "WithdrawSummaryHeader", "data": {"sections": ["zero_cost"]}},
            {"type": "Card", "data": {"children": [
                {"type": "SectionHeader", "data": {"title": "Custom"}},
                {"type": "KVRow", "data": {"label": "Key", "value": "Val"}},
            ]}},
            {"type": "ActionButton", "data": {"text": "Go", "action": {"name": "query", "args": {"queryMsg": "go"}}}},
        ])
        tc = ToolCall.create("render_a2ui", {"blocks": blocks})
        result = await tool.execute(tc, context=ctx)
        assert not result.is_error
        root = result.content["components"][0]
        root_children = root["component"]["Column"]["children"]["explicitList"]
        assert len(root_children) == 3

    @pytest.mark.asyncio
    async def test_transform_resolution_in_card_children(self, tool, ctx):
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
        text_comps = [
            c for c in result.content["components"]
            if "Text" in c.get("component", {})
            and c["component"]["Text"].get("text", {}).get("literalString") == "¥ 252,800.00"
        ]
        assert len(text_comps) == 1
