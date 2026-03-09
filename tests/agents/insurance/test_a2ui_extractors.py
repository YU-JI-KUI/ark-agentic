"""Tests for insurance a2ui extractors (withdraw_summary, withdraw_plan, policy_detail) and A2UI template compliance."""

import json
from pathlib import Path

import pytest

from ark_agentic.agents.insurance.a2ui.extractors import (
    withdraw_summary_extractor,
    withdraw_plan_extractor,
    policy_detail_extractor,
)


def test_withdraw_summary_extractor_returns_data_from_rule_engine_result() -> None:
    context = {
        "_rule_engine_result": {
            "requested_amount": 10000,
            "total_available_excl_loan": 4029.63,
            "total_available_incl_loan": 6957.76,
            "options": [
                {"product_name": "鸿利04", "survival_fund_amt": 4000, "bonus_amt": 0, "loan_amt": 1493.63, "refund_amt": 5000, "refund_fee_rate": 0.01},
                {"product_name": "鑫利", "survival_fund_amt": 29.63, "bonus_amt": 0, "loan_amt": 1434.50, "refund_amt": 3000, "refund_fee_rate": 0},
            ],
        },
        "session_id": "s1",
    }
    card_args = {"advice_text_1": "建议一", "advice_text_2": "建议二", "plan_button_text": "获取方案"}

    flat = withdraw_summary_extractor(context, card_args)

    assert flat["header_value"] == "¥ 6,957.76"
    assert flat["header_sub"] == "不含贷款可领金额：¥ 4,029.63"
    assert flat["requested_amount_display"] == "本次取款目标：¥ 10,000.00"
    assert "零成本" in flat["zero_cost_title"]
    zc = flat["zero_cost_items"]
    assert isinstance(zc, list) and len(zc) == 2
    assert zc[0]["label"] != ""
    assert zc[0]["value"] == "¥ 4,000.00"
    assert zc[1]["value"] == "¥ 29.63"
    li = flat["loan_items"]
    assert isinstance(li, list) and len(li) == 2
    assert li[0]["value"] == "¥ 1,493.63"
    assert li[1]["value"] == "¥ 1,434.50"
    assert flat["advice_text_1"] == "建议一"
    assert flat["advice_text_2"] == "建议二"
    assert flat["plan_button_text"] == "获取方案"
    assert flat["plan_action_args"] == {"queryMsg": "获取方案"}
    assert flat["zero_cost_tag"] == "不影响保障"
    assert flat["loan_tag"] == "需支付利息"
    assert li[0]["label"].endswith("可贷(年利率5%)") and " 可贷" not in li[0]["label"]
    # partial_surrender section
    ps = flat["partial_surrender_items"]
    assert isinstance(ps, list) and len(ps) == 2
    assert ps[0]["value"] == "¥ 5,000.00"
    assert "手续费" in ps[0]["label"]
    assert ps[1]["value"] == "¥ 3,000.00"
    assert "手续费" not in ps[1]["label"]
    assert flat["partial_surrender_tag"] == "保障有损失，不建议"
    assert flat["partial_surrender_total"] == "合计：¥ 8,000.00"
    assert "advice_text_3" in flat


def test_withdraw_summary_extractor_uses_fallback_when_card_args_empty() -> None:
    context = {
        "_rule_engine_result": {"total_available_excl_loan": 0, "total_available_incl_loan": 0, "options": []},
    }
    flat = withdraw_summary_extractor(context, None)

    assert flat["advice_text_1"] != ""
    assert "零成本" in flat["advice_text_1"] or "保障" in flat["advice_text_1"]
    assert flat["plan_button_text"] == "获取最优方案"
    assert flat["plan_action_args"]["queryMsg"] == "获取最优方案"
    assert flat["zero_cost_items"] == []
    assert flat["loan_items"] == []
    assert flat["partial_surrender_items"] == []
    assert "advice_text_3" in flat and flat["advice_text_3"] != ""


def test_withdraw_summary_extractor_raises_when_no_rule_engine_result() -> None:
    with pytest.raises(ValueError) as exc_info:
        withdraw_summary_extractor({}, None)
    assert "rule_engine" in str(exc_info.value)


def test_withdraw_summary_extractor_raises_when_rule_engine_result_invalid() -> None:
    with pytest.raises((ValueError, json.JSONDecodeError)):
        withdraw_summary_extractor({"_rule_engine_result": "not valid json"}, None)


def test_withdraw_summary_extractor_accepts_rule_engine_from_tool_results_by_name() -> None:
    context = {
        "_tool_results_by_name": {
            "rule_engine": {
                "total_available_excl_loan": 100,
                "total_available_incl_loan": 200,
                "options": [
                    {"product_name": "P", "survival_fund_amt": 100, "bonus_amt": 0, "loan_amt": 100},
                ],
            },
        },
    }
    flat = withdraw_summary_extractor(context, None)
    assert flat["header_value"] == "¥ 200.00"
    assert flat["zero_cost_items"][0]["value"] == "¥ 100.00"


def test_withdraw_summary_extractor_accepts_json_string_rule_engine_result() -> None:
    context = {
        "_rule_engine_result": json.dumps({
            "total_available_excl_loan": 50,
            "total_available_incl_loan": 50,
            "options": [],
        }),
    }
    flat = withdraw_summary_extractor(context, None)
    assert flat["header_value"] == "¥ 50.00"


def test_withdraw_summary_extractor_partial_surrender_fee_rate_in_label() -> None:
    context = {
        "_rule_engine_result": {
            "total_available_excl_loan": 0,
            "total_available_incl_loan": 0,
            "options": [
                {"product_name": "产品A", "survival_fund_amt": 0, "bonus_amt": 0, "loan_amt": 0, "refund_amt": 2000, "refund_fee_rate": 0.03},
                {"product_name": "产品B", "survival_fund_amt": 0, "bonus_amt": 0, "loan_amt": 0, "refund_amt": 1000, "refund_fee_rate": 0},
            ],
        },
    }
    flat = withdraw_summary_extractor(context, None)
    ps = flat["partial_surrender_items"]
    assert len(ps) == 2
    assert "手续费3%" in ps[0]["label"]
    assert "手续费" not in ps[1]["label"]


# ----- withdraw_plan_extractor -----

# Expected top-level keys for 3-plan template (plan_N_*)
def _plan_keys(n: int) -> list[str]:
    return [
        f"plan_{n}_hide", f"plan_{n}_title", f"plan_{n}_tag", f"plan_{n}_total",
        f"plan_{n}_reason", f"plan_{n}_policies", f"plan_{n}_btn_row_2_hide",
    ] + [f"plan_{n}_btn_{b}_hide" for b in range(1, 5)] + [f"plan_{n}_btn_{b}_text" for b in range(1, 5)] + [f"plan_{n}_btn_{b}_action" for b in range(1, 5)]


def test_withdraw_plan_extractor_returns_data_with_defaults() -> None:
    # Arrange: single policy with survival only, no requested_amount
    context = {
        "_rule_engine_result": {
            "options": [
                {"policy_id": "P1", "product_name": "鸿利04", "survival_fund_amt": 1000, "bonus_amt": 0, "loan_amt": 0, "refund_amt": 0},
            ],
        },
    }
    # Act
    flat = withdraw_plan_extractor(context, None)

    # Assert: global + 3 plan slots
    assert flat["page_title"] == "为您推荐的取款方案"
    assert flat["section_marker"] == "|"
    assert "prompt_text" in flat and len(flat["prompt_text"]) > 0
    for k in _plan_keys(1) + _plan_keys(2) + _plan_keys(3):
        assert k in flat, f"missing key {k}"
    # Plan 1 visible with 零成本 content
    assert flat["plan_1_hide"] is False
    assert "零成本" in flat["plan_1_title"] or "全部可用" in flat["plan_1_title"]
    assert isinstance(flat["plan_1_policies"], list) and len(flat["plan_1_policies"]) >= 1
    assert "P1" in flat["plan_1_policies"][0]["label"] and "生存金" in flat["plan_1_policies"][0]["label"]
    assert "queryMsg" in flat["plan_1_btn_1_action"]
    # Plan 2/3 hidden when only one plan generated
    assert flat["plan_2_hide"] is True
    assert flat["plan_3_hide"] is True


def test_withdraw_plan_extractor_uses_card_args_for_page_and_prompt() -> None:
    context = {
        "_rule_engine_result": {
            "options": [
                {"policy_id": "P-A", "product_name": "产品A", "survival_fund_amt": 2000, "bonus_amt": 0, "loan_amt": 0, "refund_amt": 0},
                {"policy_id": "P-B", "product_name": "产品B", "survival_fund_amt": 0, "bonus_amt": 0, "loan_amt": 1000, "refund_amt": 0},
            ],
        },
    }
    card_args = {"page_title": "自定义标题", "prompt_text": "请选择方案"}
    flat = withdraw_plan_extractor(context, card_args)

    assert flat["page_title"] == "自定义标题"
    assert flat["prompt_text"] == "请选择方案"
    assert flat["plan_1_hide"] is False
    assert isinstance(flat["plan_1_policies"], list)
    assert any("P-A" in p["label"] and "生存金" in p["label"] for p in flat["plan_1_policies"])
    # Second plan may be loan or combo depending on requested_amount; with no amount we get "全部可用渠道"
    assert isinstance(flat["plan_1_policies"], list)


def test_withdraw_plan_extractor_raises_when_no_rule_engine_data() -> None:
    with pytest.raises(ValueError) as exc_info:
        withdraw_plan_extractor({}, None)
    assert "rule_engine" in str(exc_info.value)


def test_withdraw_plan_extractor_target_allocation_caps_at_requested() -> None:
    """When user requests 10k, plan shows only 10k allocated, not full channel max."""
    context = {
        "_rule_engine_result": {
            "requested_amount": 10000,
            "options": [
                {"policy_id": "P1", "product_name": "A", "survival_fund_amt": 0, "bonus_amt": 120000, "loan_amt": 0, "refund_amt": 0},
            ],
        },
    }
    flat = withdraw_plan_extractor(context, None)

    assert flat["plan_1_hide"] is False
    assert "10000" in flat["plan_1_total"] or "10,000" in flat["plan_1_total"]
    policies = flat["plan_1_policies"]
    assert len(policies) >= 1
    # Allocated amount for bonus should be 10000, not 120000
    assert policies[0]["value"] == "¥ 10,000.00"
    assert "红利" in policies[0]["label"]


def test_withdraw_plan_extractor_max_three_plans() -> None:
    """At most 3 plans are emitted; plan_2/3 hidden when fewer generated."""
    context = {
        "_rule_engine_result": {
            "requested_amount": 50000,
            "options": [
                {"policy_id": "P1", "product_name": "A", "survival_fund_amt": 20000, "bonus_amt": 0, "loan_amt": 0, "refund_amt": 0},
                {"policy_id": "P2", "product_name": "B", "survival_fund_amt": 0, "bonus_amt": 0, "loan_amt": 40000, "refund_amt": 0},
                {"policy_id": "P3", "product_name": "C", "survival_fund_amt": 0, "bonus_amt": 0, "loan_amt": 0, "refund_amt": 60000},
            ],
        },
    }
    flat = withdraw_plan_extractor(context, None)

    visible = [n for n in (1, 2, 3) if not flat.get(f"plan_{n}_hide", True)]
    assert len(visible) <= 3, f"Expected at most 3 plans, got {visible}"
    for n in visible:
        assert flat[f"plan_{n}_total"]
        assert isinstance(flat[f"plan_{n}_policies"], list)
        assert "queryMsg" in flat[f"plan_{n}_btn_1_action"] or flat[f"plan_{n}_btn_1_hide"]


def test_withdraw_plan_extractor_insufficient_total_shows_max() -> None:
    """When total available < requested, single plan shows max possible."""
    context = {
        "_rule_engine_result": {
            "requested_amount": 500000,
            "options": [
                {"policy_id": "P1", "product_name": "A", "survival_fund_amt": 30000, "bonus_amt": 0, "loan_amt": 20000, "refund_amt": 0},
            ],
        },
    }
    flat = withdraw_plan_extractor(context, None)

    assert flat["plan_1_hide"] is False
    assert "最大可取" in flat["plan_1_title"] or "不足目标" in flat["plan_1_title"]
    assert "50,000" in flat["plan_1_total"]
    assert flat["plan_2_hide"] is True


def test_withdraw_plan_extractor_no_requested_amount_shows_all_channels() -> None:
    """When requested_amount is 0/missing, one plan aggregates all channels."""
    context = {
        "_rule_engine_result": {
            "options": [
                {"policy_id": "P1", "survival_fund_amt": 5000, "bonus_amt": 1000, "loan_amt": 0, "refund_amt": 0},
                {"policy_id": "P2", "survival_fund_amt": 0, "bonus_amt": 0, "loan_amt": 8000, "refund_amt": 0},
            ],
        },
    }
    flat = withdraw_plan_extractor(context, None)

    assert flat["plan_1_hide"] is False
    assert "全部可用" in flat["plan_1_title"]
    total_str = flat["plan_1_total"]
    assert "14,000" in total_str
    policies = flat["plan_1_policies"]
    labels = [p["label"] for p in policies]
    assert any("生存金" in l for l in labels)
    assert any("红利" in l for l in labels)
    assert any("可贷" in l or "贷款" in l for l in labels)


def test_withdraw_plan_extractor_output_keys_match_template_paths() -> None:
    """All extractor output keys are consumed by template (no orphan keys)."""
    import json
    from pathlib import Path

    tpl_path = Path(__file__).resolve().parent.parent.parent.parent / "src" / "ark_agentic" / "agents" / "insurance" / "a2ui" / "templates" / "withdraw_plan" / "template.json"
    tpl = json.loads(tpl_path.read_text(encoding="utf-8"))

    def collect_paths(obj: dict, out: set) -> None:
        if isinstance(obj, dict):
            if "path" in obj and isinstance(obj["path"], str):
                out.add(obj["path"])
            for v in obj.values():
                collect_paths(v, out)
        elif isinstance(obj, list):
            for v in obj:
                collect_paths(v, out)

    paths = set()
    collect_paths(tpl, paths)
    list_item_scope = {"label", "value"}
    template_paths = paths - list_item_scope

    ctx = {
        "_rule_engine_result": {
            "requested_amount": 10000,
            "options": [
                {"policy_id": "P1", "survival_fund_amt": 15000, "bonus_amt": 0, "loan_amt": 0, "refund_amt": 0},
            ],
        },
    }
    flat = withdraw_plan_extractor(ctx, None)
    extractor_keys = set(flat.keys())

    missing_in_extractor = template_paths - extractor_keys
    missing_in_template = extractor_keys - template_paths
    assert not missing_in_extractor, f"Template paths not in extractor: {missing_in_extractor}"
    assert not missing_in_template, f"Extractor keys not in template: {missing_in_template}"


# ----- A2UI standard compliance (withdraw_plan template) -----

_ALLOWED_A2UI_COMPONENT_TYPES = frozenset({
    "Column", "Row", "Card", "List", "Text", "Divider", "Button",
})


def test_a2ui_withdraw_plan_template_structure() -> None:
    """withdraw_plan template has required root keys and components array."""
    tpl_path = Path(__file__).resolve().parent.parent.parent.parent / "src" / "ark_agentic" / "agents" / "insurance" / "a2ui" / "templates" / "withdraw_plan" / "template.json"
    tpl = json.loads(tpl_path.read_text(encoding="utf-8"))

    assert tpl.get("event") == "beginRendering"
    assert "version" in tpl
    assert "rootComponentId" in tpl and tpl["rootComponentId"] == "root"
    assert "components" in tpl and isinstance(tpl["components"], list)
    assert "data" in tpl
    assert len(tpl["components"]) > 0


def test_a2ui_withdraw_plan_template_components_only_allowed_types() -> None:
    """Every component in withdraw_plan template uses only A2UI-standard component types."""
    tpl_path = Path(__file__).resolve().parent.parent.parent.parent / "src" / "ark_agentic" / "agents" / "insurance" / "a2ui" / "templates" / "withdraw_plan" / "template.json"
    tpl = json.loads(tpl_path.read_text(encoding="utf-8"))

    for comp in tpl["components"]:
        assert "id" in comp and "component" in comp
        inner = comp["component"]
        keys = list(inner.keys())
        assert len(keys) == 1, f"Component {comp['id']} must have exactly one type key, got {keys}"
        typ = keys[0]
        assert typ in _ALLOWED_A2UI_COMPONENT_TYPES, f"Component {comp['id']} uses non-standard type: {typ}"


def test_a2ui_withdraw_plan_list_has_child_and_datasource() -> None:
    """List components in withdraw_plan have required child and dataSource (path)."""
    tpl_path = Path(__file__).resolve().parent.parent.parent.parent / "src" / "ark_agentic" / "agents" / "insurance" / "a2ui" / "templates" / "withdraw_plan" / "template.json"
    tpl = json.loads(tpl_path.read_text(encoding="utf-8"))

    for comp in tpl["components"]:
        inner = comp["component"]
        if "List" not in inner:
            continue
        list_spec = inner["List"]
        assert "child" in list_spec, f"List {comp['id']} must have child"
        assert "dataSource" in list_spec, f"List {comp['id']} must have dataSource"
        ds = list_spec["dataSource"]
        assert isinstance(ds, dict), f"List {comp['id']} dataSource must be object"
        assert "path" in ds, f"List {comp['id']} dataSource must use path (no literalString list at root)"


def test_a2ui_withdraw_plan_button_has_action_with_name_and_args() -> None:
    """Button components have action with name and args (query event)."""
    tpl_path = Path(__file__).resolve().parent.parent.parent.parent / "src" / "ark_agentic" / "agents" / "insurance" / "a2ui" / "templates" / "withdraw_plan" / "template.json"
    tpl = json.loads(tpl_path.read_text(encoding="utf-8"))

    for comp in tpl["components"]:
        inner = comp["component"]
        if "Button" not in inner:
            continue
        btn = inner["Button"]
        assert "action" in btn, f"Button {comp['id']} must have action"
        action = btn["action"]
        assert action.get("name") == "query", f"Button {comp['id']} action must be query"
        assert "args" in action, f"Button {comp['id']} action must have args"
        assert "path" in action["args"], f"Button {comp['id']} action.args must bind via path"


def test_a2ui_withdraw_plan_hide_uses_path() -> None:
    """Components with hide property use path binding (dynamic)."""
    tpl_path = Path(__file__).resolve().parent.parent.parent.parent / "src" / "ark_agentic" / "agents" / "insurance" / "a2ui" / "templates" / "withdraw_plan" / "template.json"
    tpl = json.loads(tpl_path.read_text(encoding="utf-8"))

    for comp in tpl["components"]:
        inner = comp["component"]
        for typ, spec in inner.items():
            if not isinstance(spec, dict):
                continue
            if "hide" not in spec:
                continue
            hide_val = spec["hide"]
            assert isinstance(hide_val, dict), f"{comp['id']}.{typ}.hide must be object"
            assert "path" in hide_val, f"{comp['id']}.{typ}.hide must use path for dynamic binding"


# ----- policy_detail_extractor -----


def test_policy_detail_extractor_one_policy() -> None:
    context = {
        "_rule_engine_result": {
            "options": [
                {
                    "policy_id": "P1",
                    "product_name": "鸿利04",
                    "policy_year": 6,
                    "survival_fund_amt": 4000,
                    "bonus_amt": 0,
                    "loan_amt": 1493.63,
                    "refund_amt": 0,
                    "available_amount": 5493.63,
                },
            ],
        },
    }
    flat = policy_detail_extractor(context, None)

    assert flat["page_title"] == "您的保单详情"
    policies = flat["policies"]
    assert isinstance(policies, list) and len(policies) == 1
    assert policies[0]["title"] == "鸿利04"
    assert policies[0]["total_value"] == "¥ 5,493.63"


def test_policy_detail_extractor_three_policies_sorted_by_amount() -> None:
    context = {
        "_rule_engine_result": {
            "options": [
                {"policy_id": "P1", "product_name": "A", "policy_year": 1, "survival_fund_amt": 100, "bonus_amt": 0, "loan_amt": 0, "refund_amt": 0, "available_amount": 100},
                {"policy_id": "P2", "product_name": "B", "policy_year": 2, "survival_fund_amt": 200, "bonus_amt": 0, "loan_amt": 0, "refund_amt": 0, "available_amount": 200},
                {"policy_id": "P3", "product_name": "C", "policy_year": 3, "survival_fund_amt": 300, "bonus_amt": 0, "loan_amt": 0, "refund_amt": 0, "available_amount": 300},
            ],
        },
    }
    flat = policy_detail_extractor(context, None)

    policies = flat["policies"]
    assert len(policies) == 3
    assert policies[0]["title"] == "C"
    assert policies[1]["title"] == "B"
    assert policies[2]["title"] == "A"
    assert policies[0]["total_value"] == "¥ 300.00"
    assert policies[1]["total_value"] == "¥ 200.00"
    assert policies[2]["total_value"] == "¥ 100.00"


def test_policy_detail_extractor_empty_options() -> None:
    context = {"_rule_engine_result": {"options": []}}
    flat = policy_detail_extractor(context, None)

    assert flat["policies"] == []
    assert flat["prompt_text"] != ""


def test_policy_detail_extractor_raises_when_no_policy_data() -> None:
    with pytest.raises(ValueError) as exc_info:
        policy_detail_extractor({}, None)
    assert "保单" in str(exc_info.value) or "rule_engine" in str(exc_info.value)


# ----- Integration: render_card with real insurance extractors -----


@pytest.fixture
def _minimal_rule_engine_context() -> dict:
    return {
        "_rule_engine_result": {
            "requested_amount": 1000,
            "total_available_excl_loan": 1000,
            "total_available_incl_loan": 1000,
            "options": [
                {
                    "policy_id": "P1",
                    "product_name": "测试产品",
                    "policy_year": 1,
                    "survival_fund_amt": 1000,
                    "bonus_amt": 0,
                    "loan_amt": 0,
                    "refund_amt": 0,
                    "available_amount": 1000,
                },
            ],
        },
    }


@pytest.mark.asyncio
async def test_insurance_render_card_all_three_types_render_successfully(
    _minimal_rule_engine_context: dict,
) -> None:
    """RenderCardTool with real insurance extractors + templates for all 3 card_types."""
    from pathlib import Path

    from ark_agentic.agents.insurance.a2ui.extractors import (
        policy_detail_extractor,
        withdraw_plan_extractor,
        withdraw_summary_extractor,
    )
    from ark_agentic.core.tools import RenderCardTool
    from ark_agentic.core.types import ToolCall

    template_root = (
        Path(__file__).resolve().parent.parent.parent.parent
        / "src"
        / "ark_agentic"
        / "agents"
        / "insurance"
        / "a2ui"
        / "templates"
    )
    tool = RenderCardTool(
        template_root=template_root,
        extractors={
            "withdraw_summary": withdraw_summary_extractor,
            "withdraw_plan": withdraw_plan_extractor,
            "policy_detail": policy_detail_extractor,
        },
    )
    ctx = {**_minimal_rule_engine_context, "session_id": "s1"}

    for card_type in ("withdraw_summary", "withdraw_plan", "policy_detail"):
        tc = ToolCall(id=f"tc-{card_type}", name="render_card", arguments={"card_type": card_type})
        result = await tool.execute(tc, ctx)
        assert not result.is_error, f"{card_type}: {result.content}"
        assert result.content.get("event") == "beginRendering"
        assert result.content.get("surfaceId", "").startswith(card_type)
        assert "components" in result.content and len(result.content["components"]) > 0
        assert "data" in result.content
