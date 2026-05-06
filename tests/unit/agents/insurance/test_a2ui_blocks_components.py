"""Tests for insurance A2UI blocks, components, and the agent pipeline."""

import json

import pytest

from ark_agentic.agents.insurance.a2ui.blocks import INSURANCE_BLOCKS
from ark_agentic.agents.insurance.a2ui.components import INSURANCE_COMPONENTS
from ark_agentic.core.a2ui.theme import A2UITheme
from ark_agentic.core.tools.render_a2ui import BlocksConfig, RenderA2UITool

# Default-theme builders (registry entries from create_insurance_* factory)
build_section_header = INSURANCE_BLOCKS["SectionHeader"]
build_kv_row = INSURANCE_BLOCKS["KVRow"]
build_accent_total = INSURANCE_BLOCKS["AccentTotal"]
build_hint_text = INSURANCE_BLOCKS["HintText"]
build_action_button = INSURANCE_BLOCKS["ActionButton"]
build_divider = INSURANCE_BLOCKS["Divider"]

build_withdraw_summary_header = INSURANCE_COMPONENTS["WithdrawSummaryHeader"]
build_withdraw_summary_section = INSURANCE_COMPONENTS["WithdrawSummarySection"]
build_withdraw_plan_card = INSURANCE_COMPONENTS["WithdrawPlanCard"]
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
            {"section_name": "zero_cost"},
            _id_gen(),
            _SAMPLE_RAW_DATA,
        )
        assert len(output.components) > 0
        card = output.components[0]
        assert "Card" in card["component"]

    def test_loan(self):
        output = build_withdraw_summary_section(
            {"section_name": "loan"},
            _id_gen(),
            _SAMPLE_RAW_DATA,
        )
        assert len(output.components) > 0

    def test_surrender_total_color_is_gray(self):
        raw = {
            "options": [
                {"policy_id": "P1", "product_name": "X", "product_type": "whole_life",
                 "survival_fund_amt": 0, "bonus_amt": 0, "loan_amt": 0, "refund_amt": 5000},
            ]
        }
        output = build_withdraw_summary_section(
            {"section_name": "surrender"}, _id_gen(), raw,
        )
        total_texts = [c for c in output.components if "Text" in c.get("component", {})
                       and c["component"]["Text"].get("bold") is True
                       and "合计" in str(c["component"]["Text"].get("text", {}).get("literalString", ""))]
        assert len(total_texts) == 1
        assert total_texts[0]["component"]["Text"]["color"] == "#999999"

    def test_zero_cost_total_color_is_accent(self):
        output = build_withdraw_summary_section(
            {"section_name": "zero_cost"}, _id_gen(), _SAMPLE_RAW_DATA,
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
            {"section_name": "loan"},
            _id_gen(),
            data_no_loan,
        )
        assert output.components == []

    def test_bonus_preset_excludes_survival_fund(self):
        """POL002 has both survival_fund and bonus; section=bonus must not list 生存金."""
        output = build_withdraw_summary_section(
            {"section_name": "bonus"},
            _id_gen(),
            _SAMPLE_RAW_DATA,
        )
        assert len(output.components) > 0
        assert "红利" in output.llm_digest
        assert "生存金" not in output.llm_digest

    def test_survival_fund_preset_excludes_bonus(self):
        """POL002 has both; section=survival_fund must not list 红利."""
        output = build_withdraw_summary_section(
            {"section_name": "survival_fund"},
            _id_gen(),
            _SAMPLE_RAW_DATA,
        )
        assert len(output.components) > 0
        assert "生存金" in output.llm_digest
        assert "红利" not in output.llm_digest


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

    def test_title_derived_from_actual_channels_single(self):
        """单渠道分配 → title 由引擎根据 actual_channels 派生，LLM 不再传 title/tag。"""
        output = build_withdraw_plan_card(
            {"channels": ["survival_fund"], "target": 5000, "is_recommended": True},
            _id_gen(), _SAMPLE_RAW_DATA,
        )
        title_texts = [c["component"]["Text"]["text"]["literalString"]
                       for c in output.components if "Text" in c.get("component", {})
                       and "★ 推荐" in str(c["component"]["Text"].get("text", {}).get("literalString", ""))]
        assert any("生存金领取" in t for t in title_texts)

    def test_title_does_not_lie_about_unallocated_channels(self):
        """Q1 回归：LLM 传 channels=[sf,bonus,policy_loan] target=10000 时，
        target 在 sf 满足，title 一定不能含'贷款'字样。"""
        output = build_withdraw_plan_card(
            {"channels": ["survival_fund", "bonus", "policy_loan"], "target": 10000,
             "is_recommended": True},
            _id_gen(), _SAMPLE_RAW_DATA,
        )
        title_text = " ".join(
            str(c["component"]["Text"].get("text", {}).get("literalString", ""))
            for c in output.components if "Text" in c.get("component", {})
        )
        assert "贷款" not in title_text
        assert "生存金" in title_text
        # digest 也只展开实际使用的 channel
        assert "policy_loan" not in output.llm_digest
        assert "bonus" not in output.llm_digest

    def test_tag_color_loan_orange(self):
        """单渠道贷款 → tag 颜色为橙色（#FF8800）。"""
        output = build_withdraw_plan_card(
            {"channels": ["policy_loan"], "target": 5000, "is_recommended": False},
            _id_gen(), _SAMPLE_RAW_DATA,
        )
        tag_texts = [c for c in output.components if "Text" in c.get("component", {})
                     and "需支付利息" in str(c["component"]["Text"].get("text", {}).get("literalString", ""))]
        assert len(tag_texts) == 1
        assert tag_texts[0]["component"]["Text"]["color"] == "#FF8800"

    def test_tag_color_zero_cost_green(self):
        """零成本组合（sf+bonus 都被分配）→ tag 为不影响保障 + 绿色。"""
        # target=17000 必须 sf(12000)+bonus(5000) 才够 → 两个渠道都被分配
        output = build_withdraw_plan_card(
            {"channels": ["survival_fund", "bonus"], "target": 17000, "is_recommended": True},
            _id_gen(), _SAMPLE_RAW_DATA,
        )
        tag_texts = [c for c in output.components if "Text" in c.get("component", {})
                     and "不影响保障" in str(c["component"]["Text"].get("text", {}).get("literalString", ""))]
        assert len(tag_texts) == 1
        assert tag_texts[0]["component"]["Text"]["color"] == "#6cb585"

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

    def test_state_delta_clears_submitted_channels(self):
        output = build_withdraw_plan_card(
            {"channels": ["survival_fund", "bonus"], "target": 10000, "title": "T"},
            _id_gen(), _SAMPLE_RAW_DATA,
        )
        assert output.state_delta["_submitted_channels"] == []

    def test_channels_null_uses_all(self):
        output = build_withdraw_plan_card(
            {"target": 5000, "title": "T"},
            _id_gen(), _SAMPLE_RAW_DATA,
        )
        assert len(output.components) > 0
        assert output.state_delta is not None

    def test_digest_contains_channels_and_total(self):
        """llm_digest 必须以 `[卡片:方案` 锚点开头且含 channels=[…] / total=… 字段。"""
        output = build_withdraw_plan_card(
            {"channels": ["survival_fund", "bonus"], "target": 50000, "title": "零成本"},
            _id_gen(), _SAMPLE_RAW_DATA,
        )
        assert output.llm_digest.startswith("[卡片:方案")
        assert "channels=[" in output.llm_digest
        assert "survival_fund" in output.llm_digest
        assert "bonus" in output.llm_digest
        assert "total=" in output.llm_digest

    def test_digest_amount_matches_actual_allocation(self):
        """Digest total must match the actual allocated amount, not the target."""
        output = build_withdraw_plan_card(
            {"channels": ["survival_fund"], "target": 50000, "title": "T"},
            _id_gen(), _SAMPLE_RAW_DATA,
        )
        assert "¥12,000.00" in output.llm_digest, (
            f"survival_fund max is 12000 in sample data; digest={output.llm_digest}"
        )

    def test_state_delta_plan_allocations_structure(self):
        """_plan_allocations must contain channels and allocations with policy_no/channel/amount."""
        output = build_withdraw_plan_card(
            {"channels": ["survival_fund", "bonus"], "target": 10000, "title": "T"},
            _id_gen(), _SAMPLE_RAW_DATA,
        )
        allocs = output.state_delta["_plan_allocations"]
        assert isinstance(allocs, list) and len(allocs) == 1
        plan = allocs[0]
        assert "channels" in plan
        assert "allocations" in plan
        for a in plan["allocations"]:
            assert "channel" in a and "policy_no" in a and "amount" in a

    def test_new_plan_card_always_resets_submitted_channels(self):
        """Any new PlanCard must reset _submitted_channels to [], even if channels differ."""
        for channels in [
            ["survival_fund"],
            ["policy_loan"],
            ["survival_fund", "bonus", "policy_loan"],
        ]:
            output = build_withdraw_plan_card(
                {"channels": channels, "target": 5000, "title": "T"},
                _id_gen(), _SAMPLE_RAW_DATA,
            )
            assert output.state_delta["_submitted_channels"] == [], (
                f"channels={channels} must reset _submitted_channels"
            )

    def test_single_channel_plan_digest_amount_not_zero(self):
        """Single-channel PlanCard with target=0 (directive) shows actual available, not 0."""
        output = build_withdraw_plan_card(
            {"channels": ["survival_fund"], "target": 0, "is_recommended": True},
            _id_gen(), _SAMPLE_RAW_DATA,
        )
        assert "¥0" not in output.llm_digest
        assert "¥12,000.00" in output.llm_digest


class TestDeriveTitleTag:
    """覆盖 _derive_title_tag 的 6 类组合（通过 build_withdraw_plan_card 间接验证）。"""

    def _title_of(self, output) -> str:
        return " ".join(
            str(c["component"]["Text"].get("text", {}).get("literalString", ""))
            for c in output.components if "Text" in c.get("component", {})
        )

    @pytest.mark.parametrize("channel,expect_title,expect_tag", [
        ("survival_fund",      "生存金领取", "不影响保障"),
        ("bonus",              "红利领取",   "不影响保障"),
        ("policy_loan",        "保单贷款",   "需支付利息"),
        ("partial_withdrawal", "部分领取",   "保额会降低"),
    ])
    def test_single_channel_titles(self, channel, expect_title, expect_tag):
        raw = {
            "options": [
                {
                    "policy_id": "P1", "product_name": "X", "product_type": "annuity",
                    "policy_year": 6,
                    "survival_fund_amt": 1000, "bonus_amt": 1000,
                    "loan_amt": 1000, "refund_amt": 1000, "refund_fee_rate": 0,
                }
            ]
        }
        output = build_withdraw_plan_card(
            {"channels": [channel], "target": 500, "is_recommended": True},
            _id_gen(), raw,
        )
        text = self._title_of(output)
        assert "★ 推荐" in text
        assert expect_title in text
        assert expect_tag in text

    def test_surrender_single_channel(self):
        """退保需要 product_type=whole_life。"""
        raw = {
            "options": [
                {
                    "policy_id": "P1", "product_name": "终身寿", "product_type": "whole_life",
                    "policy_year": 8,
                    "survival_fund_amt": 0, "bonus_amt": 0,
                    "loan_amt": 0, "refund_amt": 50000, "refund_fee_rate": 0,
                }
            ]
        }
        output = build_withdraw_plan_card(
            {"channels": ["surrender"], "target": 10000, "is_recommended": False},
            _id_gen(), raw,
        )
        text = self._title_of(output)
        assert "退保" in text
        assert "保障终止" in text
        assert "★ 推荐" not in text

    def test_zero_cost_combo(self):
        """sf+bonus 同时被分配 → 零成本领取。"""
        output = build_withdraw_plan_card(
            {"channels": ["survival_fund", "bonus"], "target": 15000, "is_recommended": True},
            _id_gen(), _SAMPLE_RAW_DATA,
        )
        text = self._title_of(output)
        assert "★ 推荐" in text
        assert "零成本领取" in text
        assert "不影响保障" in text

    def test_combo_with_loan_titled_loan(self):
        """组合含贷款 → 含保单贷款方案 / 需支付利息。"""
        # target=20000 由 sf(12000)+bonus(5200)+loan(剩 2800) 组成
        output = build_withdraw_plan_card(
            {"channels": ["survival_fund", "bonus", "policy_loan"],
             "target": 20000, "is_recommended": False},
            _id_gen(), _SAMPLE_RAW_DATA,
        )
        text = self._title_of(output)
        assert "含保单贷款方案" in text
        assert "需支付利息" in text

    def test_combo_with_partial_titled_combo(self):
        """组合含 partial 不含 loan/surrender → 组合领取方案 / 保额会降低。"""
        # target=20000 由 sf(12000)+bonus(5200)+partial(2800) 组成
        output = build_withdraw_plan_card(
            {"channels": ["survival_fund", "bonus", "partial_withdrawal"],
             "target": 20000, "is_recommended": True},
            _id_gen(), _SAMPLE_RAW_DATA,
        )
        text = self._title_of(output)
        assert "★ 推荐" in text
        assert "组合领取方案" in text
        assert "保额会降低" in text

    def test_recommended_prefix_only_when_flag_true(self):
        output_true = build_withdraw_plan_card(
            {"channels": ["survival_fund"], "target": 5000, "is_recommended": True},
            _id_gen(), _SAMPLE_RAW_DATA,
        )
        output_false = build_withdraw_plan_card(
            {"channels": ["survival_fund"], "target": 5000, "is_recommended": False},
            _id_gen(), _SAMPLE_RAW_DATA,
        )
        assert "★ 推荐" in self._title_of(output_true)
        assert "★ 推荐" not in self._title_of(output_false)


# ============ Agent Pipeline (Card expansion) ============


class TestAgentPipeline:
    @pytest.fixture
    def tool(self):
        return RenderA2UITool(
            blocks=BlocksConfig(
                agent_blocks=INSURANCE_BLOCKS,
                agent_components=INSURANCE_COMPONENTS,
                theme=A2UITheme(root_gap=16, root_padding=[16, 32, 16, 16]),
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
        blocks = [
            {"type": "Card", "data": {"children": [
                {"type": "SectionHeader", "data": {"title": "保单A"}},
                {"type": "KVRow", "data": {"label": "生存金", "value": "¥ 12,000"}},
                {"type": "Divider"},
                {"type": "AccentTotal", "data": {"label": "合计", "value": "¥ 12,000"}},
            ]}},
        ]
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
        blocks = [
            {"type": "Card", "data": {"children": [
                {"type": "Card", "data": {"children": [
                    {"type": "KVRow", "data": {"label": "A", "value": "B"}},
                ]}},
            ]}},
        ]
        tc = ToolCall.create("render_a2ui", {"blocks": blocks})
        result = await tool.execute(tc, context=ctx)
        assert not result.is_error
        card_comps = [c for c in result.content["components"] if "Card" in c.get("component", {})]
        assert len(card_comps) == 2

    @pytest.mark.asyncio
    async def test_card_max_depth_exceeded(self, tool, ctx):
        blocks = [
            {"type": "Card", "data": {"children": [
                {"type": "Card", "data": {"children": [
                    {"type": "Card", "data": {"children": [
                        {"type": "Card", "data": {"children": [
                            {"type": "KVRow", "data": {"label": "A", "value": "B"}},
                        ]}},
                    ]}},
                ]}},
            ]}},
        ]
        tc = ToolCall.create("render_a2ui", {"blocks": blocks})
        result = await tool.execute(tc, context=ctx)
        assert result.is_error
        assert "嵌套" in result.content

    @pytest.mark.asyncio
    async def test_component_in_pipeline(self, tool, ctx):
        blocks = [
            {"type": "WithdrawSummaryHeader", "data": {"sections": ["zero_cost"]}},
            {"type": "WithdrawSummarySection", "data": {"section_name": "zero_cost"}},
        ]
        tc = ToolCall.create("render_a2ui", {"blocks": blocks})
        result = await tool.execute(tc, context=ctx)
        assert not result.is_error
        card_comps = [c for c in result.content["components"] if "Card" in c.get("component", {})]
        assert len(card_comps) >= 2

    @pytest.mark.asyncio
    async def test_mixed_blocks_and_components(self, tool, ctx):
        blocks = [
            {"type": "WithdrawSummaryHeader", "data": {"sections": ["zero_cost"]}},
            {"type": "Card", "data": {"children": [
                {"type": "SectionHeader", "data": {"title": "Custom"}},
                {"type": "KVRow", "data": {"label": "Key", "value": "Val"}},
            ]}},
            {"type": "ActionButton", "data": {"text": "Go", "action": {"name": "query", "args": {"queryMsg": "go"}}}},
        ]
        tc = ToolCall.create("render_a2ui", {"blocks": blocks})
        result = await tool.execute(tc, context=ctx)
        assert not result.is_error
        root = result.content["components"][0]
        root_children = root["component"]["Column"]["children"]["explicitList"]
        assert len(root_children) == 3

    @pytest.mark.asyncio
    async def test_plan_card_pipeline_clears_submitted_channels(self, tool, ctx):
        blocks = [
            {"type": "WithdrawPlanCard", "data": {
                "channels": ["survival_fund", "bonus"], "target": 10000, "title": "Zero-cost",
            }},
        ]
        tc = ToolCall.create("render_a2ui", {"blocks": blocks})
        result = await tool.execute(tc, context=ctx)
        assert not result.is_error
        assert result.metadata["state_delta"]["_submitted_channels"] == []

    @pytest.mark.asyncio
    async def test_plan_card_pipeline_digest_propagates(self, tool, ctx):
        """render_a2ui 必须透传 PlanCard 的 `[卡片:方案 …]` 锚点 digest 供后续 skill 判定。"""
        blocks = [
            {"type": "WithdrawPlanCard", "data": {
                "channels": ["survival_fund", "bonus"], "target": 10000, "title": "零成本领取",
            }},
        ]
        tc = ToolCall.create("render_a2ui", {"blocks": blocks})
        result = await tool.execute(tc, context=ctx)
        assert not result.is_error
        digest = result.llm_digest
        assert digest is not None, "render_a2ui must propagate llm_digest from PlanCard"
        assert digest.startswith("[卡片:方案")
        assert "channels=[" in digest
        assert "survival_fund" in digest
        assert "total=" in digest

    @pytest.mark.asyncio
    async def test_plan_card_pipeline_state_delta_resets_on_new_card(self, tool, ctx):
        """New PlanCard via pipeline must reset _submitted_channels even if prior state had submissions."""
        blocks = [
            {"type": "WithdrawPlanCard", "data": {
                "channels": ["policy_loan"], "target": 5000, "title": "贷款方案",
            }},
        ]
        tc = ToolCall.create("render_a2ui", {"blocks": blocks})
        result = await tool.execute(tc, context=ctx)
        assert not result.is_error
        delta = result.metadata.get("state_delta", {})
        assert delta.get("_submitted_channels") == [], (
            "New PlanCard must reset _submitted_channels"
        )

    @pytest.mark.asyncio
    async def test_transform_resolution_in_card_children(self, tool, ctx):
        blocks = [
            {"type": "Card", "data": {"children": [
                {"type": "KVRow", "data": {
                    "label": "Total",
                    "value": {"get": "total_available_incl_loan", "format": "currency"},
                }},
            ]}},
        ]
        tc = ToolCall.create("render_a2ui", {"blocks": blocks})
        result = await tool.execute(tc, context=ctx)
        assert not result.is_error
        text_comps = [
            c for c in result.content["components"]
            if "Text" in c.get("component", {})
            and c["component"]["Text"].get("text", {}).get("literalString") == "¥ 252,800.00"
        ]
        assert len(text_comps) == 1
