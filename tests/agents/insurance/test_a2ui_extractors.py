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
    card_args = None  # card_args no longer used for withdraw_summary

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
    assert flat["zero_cost_hide"] is False
    li = flat["loan_items"]
    assert isinstance(li, list) and len(li) == 2
    assert li[0]["value"] == "¥ 1,493.63"
    assert li[1]["value"] == "¥ 1,434.50"
    assert flat["loan_hide"] is False
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
    assert flat["partial_surrender_hide"] is False
    assert flat["partial_surrender_tag"] == "保障有损失，不建议"
    assert flat["partial_surrender_total"] == "合计：¥ 8,000.00"


def test_withdraw_summary_extractor_empty_options_sets_hide_true() -> None:
    context = {
        "_rule_engine_result": {"total_available_excl_loan": 0, "total_available_incl_loan": 0, "options": []},
    }
    flat = withdraw_summary_extractor(context, None)

    assert flat["zero_cost_items"] == []
    assert flat["loan_items"] == []
    assert flat["partial_surrender_items"] == []
    assert flat["zero_cost_hide"] is True
    assert flat["loan_hide"] is True
    assert flat["partial_surrender_hide"] is True
    assert flat["header_value"] == "¥ 0.00"


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
    assert flat["partial_surrender_hide"] is False
    assert flat["zero_cost_hide"] is True
    assert flat["loan_hide"] is True


def test_withdraw_summary_extractor_hide_only_when_channel_empty() -> None:
    """Only zero_cost has items → zero_cost_hide False, loan_hide and partial_surrender_hide True."""
    context = {
        "_rule_engine_result": {
            "total_available_excl_loan": 100,
            "total_available_incl_loan": 100,
            "options": [
                {"product_name": "P", "survival_fund_amt": 100, "bonus_amt": 0, "loan_amt": 0, "refund_amt": 0},
            ],
        },
    }
    flat = withdraw_summary_extractor(context, None)
    assert flat["zero_cost_hide"] is False
    assert len(flat["zero_cost_items"]) == 1
    assert flat["loan_hide"] is True
    assert flat["partial_surrender_hide"] is True


# ----- withdraw_plan_extractor -----

# Expected top-level keys for 3-plan template (plan_N_*)
def _plan_keys(n: int) -> list[str]:
    return [
        f"plan_{n}_hide", f"plan_{n}_title", f"plan_{n}_tag", f"plan_{n}_tag_hide",
        f"plan_{n}_total", f"plan_{n}_reason", f"plan_{n}_policies",
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
    assert flat["section_marker"] == "|"
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


def test_withdraw_plan_extractor_uses_card_args_for_plans() -> None:
    context = {
        "_rule_engine_result": {
            "options": [
                {"policy_id": "P-A", "product_name": "产品A", "survival_fund_amt": 2000, "bonus_amt": 0, "loan_amt": 0, "refund_amt": 0},
                {"policy_id": "P-B", "product_name": "产品B", "survival_fund_amt": 0, "bonus_amt": 0, "loan_amt": 1000, "refund_amt": 0},
            ],
        },
    }
    flat = withdraw_plan_extractor(context, {"plans": None})

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
    # With new priority logic: Plan 1 is combo (zc 20k + loan 30k = 50k), no alternatives since combo
    assert flat["plan_1_hide"] is False
    assert "★ 推荐" in flat["plan_1_title"]
    for n in visible:
        assert flat[f"plan_{n}_total"]
        assert isinstance(flat[f"plan_{n}_policies"], list)
        assert "queryMsg" in flat[f"plan_{n}_btn_1_action"] or flat[f"plan_{n}_btn_1_hide"]


def test_withdraw_plan_extractor_priority_combo_over_risk_only() -> None:
    """Plan 1 uses priority combo: partial_withdrawal before policy_loan (matches SKILL.md order)."""
    context = {
        "_rule_engine_result": {
            "requested_amount": 60000,
            "options": [
                {"policy_id": "P1", "product_name": "金瑞人生", "product_type": "annuity",
                 "survival_fund_amt": 12000, "bonus_amt": 5200, "loan_amt": 0, "refund_amt": 160000},
                {"policy_id": "P2", "product_name": "智盈人生", "product_type": "universal",
                 "survival_fund_amt": 0, "bonus_amt": 0, "loan_amt": 0, "refund_amt": 85000},
                {"policy_id": "P3", "product_name": "平安福", "product_type": "whole_life",
                 "survival_fund_amt": 0, "bonus_amt": 0, "loan_amt": 33600, "refund_amt": 42000},
            ],
        },
    }
    flat = withdraw_plan_extractor(context, None)

    assert flat["plan_1_hide"] is False
    assert "★ 推荐" in flat["plan_1_title"]

    # New priority order: partial_withdrawal before policy_loan
    # Allocation: survival(12k) + bonus(5.2k) + partial_P1(42.8k) = 60k  (loan NOT used)
    policies = flat["plan_1_policies"]
    total_alloc = sum(float(p["value"].replace("¥", "").replace(",", "").strip()) for p in policies)
    assert abs(total_alloc - 60000) < 1, f"Expected 60k allocation, got {total_alloc}"

    labels = [p["label"] for p in policies]
    assert any("生存金" in l for l in labels), "survival_fund should be allocated first"
    assert any("红利" in l for l in labels), "bonus should be allocated"
    assert any("部分领取" in l for l in labels), "partial_withdrawal should be used before loan"
    # loan should NOT be used since partial_withdrawal satisfies the remaining amount
    assert not any("贷款" in l for l in labels), "policy_loan should NOT be used when partial covers it"

    btn_texts = [flat[f"plan_1_btn_{i}_text"] for i in range(1, 5) if not flat[f"plan_1_btn_{i}_hide"]]
    assert len(btn_texts) >= 2, f"Combo plan should have multiple buttons, got {btn_texts}"

    # Plan 2/3 hidden (Plan 1 is combo)
    assert flat["plan_2_hide"] is True
    assert flat["plan_3_hide"] is True


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


# ----- withdraw_plan_extractor with card_args.plans (LLM-driven) -----


def test_withdraw_plan_extractor_with_plans_spec_autofill_when_channels_insufficient() -> None:
    """Key bug fix: when preferred channels can't meet target, extractor auto-fills to reach it."""
    context = {
        "_rule_engine_result": {
            "requested_amount": 30000,
            "options": [
                # zero-cost: 17,200 total (insufficient for 30k)
                {"policy_id": "P1", "product_name": "A", "product_type": "annuity",
                 "survival_fund_amt": 12000, "bonus_amt": 5200, "loan_amt": 0, "refund_amt": 50000},
            ],
        },
    }
    card_args = {
        "plans": [
            {"title": "★ 推荐: 零成本优先", "tag": "(不影响保障优先)", "reason": "零成本优先",
             "channels": ["survival_fund", "bonus"]},
        ]
    }
    flat = withdraw_plan_extractor(context, card_args)

    assert flat["plan_1_hide"] is False
    policies = flat["plan_1_policies"]
    total_alloc = sum(float(p["value"].replace("¥", "").replace(",", "").strip()) for p in policies)
    # Auto-fill should have added partial_withdrawal to reach 30,000
    assert abs(total_alloc - 30000) < 1, f"Expected 30k after auto-fill, got {total_alloc}"
    labels = [p["label"] for p in policies]
    assert any("生存金" in l for l in labels), "survival_fund should be in allocation"
    assert any("红利" in l for l in labels), "bonus should be in allocation"
    assert any("部分领取" in l for l in labels), "partial_withdrawal auto-filled to reach target"


def test_withdraw_plan_extractor_with_plans_spec_autofill_respects_exclude_channels() -> None:
    """exclude_channels prevents auto-fill from using the excluded channel."""
    context = {
        "_rule_engine_result": {
            "requested_amount": 30000,
            "options": [
                {"policy_id": "P1", "product_name": "A", "product_type": "annuity",
                 "survival_fund_amt": 12000, "bonus_amt": 5200, "loan_amt": 20000, "refund_amt": 50000},
            ],
        },
    }
    card_args = {
        "plans": [
            {
                "title": "★ 推荐（不含贷款）",
                "tag": "(不含贷款)",
                "reason": "排除贷款渠道",
                "channels": ["survival_fund", "bonus"],
                "exclude_channels": ["policy_loan"],
            }
        ]
    }
    flat = withdraw_plan_extractor(context, card_args)

    assert flat["plan_1_hide"] is False
    policies = flat["plan_1_policies"]
    labels = [p["label"] for p in policies]
    # loan must NOT appear despite being available
    assert not any("贷款" in l for l in labels), "policy_loan must be excluded even during auto-fill"
    # partial_withdrawal should be used instead
    assert any("部分领取" in l for l in labels), "partial_withdrawal should fill the gap"
    total_alloc = sum(float(p["value"].replace("¥", "").replace(",", "").strip()) for p in policies)
    assert abs(total_alloc - 30000) < 1, f"Expected 30k after auto-fill (no loan), got {total_alloc}"


def test_withdraw_plan_extractor_with_plans_spec_autofill_impossible_shows_max() -> None:
    """When all non-excluded channels still can't meet target, show honest maximum."""
    context = {
        "_rule_engine_result": {
            "requested_amount": 30000,
            "options": [
                {"policy_id": "P1", "product_name": "A", "product_type": "annuity",
                 "survival_fund_amt": 12000, "bonus_amt": 5200, "loan_amt": 0, "refund_amt": 0},
            ],
        },
    }
    card_args = {
        "plans": [
            {
                "title": "★ 只用零成本",
                "tag": "(不影响保障)",
                "reason": "仅零成本渠道",
                "channels": ["survival_fund", "bonus"],
                "exclude_channels": ["partial_withdrawal", "policy_loan", "surrender"],
            }
        ]
    }
    flat = withdraw_plan_extractor(context, card_args)

    assert flat["plan_1_hide"] is False
    total_alloc = sum(float(p["value"].replace("¥", "").replace(",", "").strip()) for p in flat["plan_1_policies"])
    # Only 17,200 available; plan honestly shows that, not 30,000
    assert abs(total_alloc - 17200) < 1, f"Expected honest max 17,200, got {total_alloc}"
    assert "30,000" not in flat["plan_1_total"], "Should not show target when it's unreachable"


def test_withdraw_plan_extractor_with_plans_spec_no_autofill_when_sufficient() -> None:
    """When channels already meet target, no extra channels are added (deterministic)."""
    context = {
        "_rule_engine_result": {
            "requested_amount": 10000,
            "options": [
                {"policy_id": "P1", "product_name": "A", "product_type": "annuity",
                 "survival_fund_amt": 15000, "bonus_amt": 5000, "loan_amt": 8000, "refund_amt": 20000},
            ],
        },
    }
    card_args = {
        "plans": [
            {"title": "★ 零成本", "tag": "", "reason": "足够", "channels": ["survival_fund", "bonus"]},
        ]
    }
    flat = withdraw_plan_extractor(context, card_args)

    assert flat["plan_1_hide"] is False
    labels = [p["label"] for p in flat["plan_1_policies"]]
    # Only zero-cost channels should appear; no auto-fill needed
    assert not any("贷款" in l for l in labels), "No auto-fill when channels are sufficient"
    assert not any("部分" in l for l in labels), "No auto-fill when channels are sufficient"
    assert "10,000" in flat["plan_1_total"]


def test_withdraw_plan_extractor_with_plans_spec_basic() -> None:
    """LLM-specified channels are respected; only those channels are allocated."""
    context = {
        "_rule_engine_result": {
            "requested_amount": 10000,
            "options": [
                {"policy_id": "P1", "product_name": "A", "survival_fund_amt": 8000, "bonus_amt": 3000, "loan_amt": 5000, "refund_amt": 0},
            ],
        },
    }
    card_args = {
        "plans": [
            {"title": "★ 推荐: 零成本", "tag": "(不影响保障)", "reason": "零成本优先", "channels": ["survival_fund", "bonus"]},
        ]
    }
    flat = withdraw_plan_extractor(context, card_args)

    assert flat["plan_1_hide"] is False
    assert flat["plan_1_title"] == "★ 推荐: 零成本"
    assert flat["plan_1_tag"] == "(不影响保障)"
    labels = [p["label"] for p in flat["plan_1_policies"]]
    assert any("生存金" in l for l in labels)
    assert any("红利" in l for l in labels)
    # loan NOT in spec → should not appear
    assert not any("贷款" in l for l in labels)
    # total should be capped at actual available in those channels (8000+2000=10000)
    assert "10,000" in flat["plan_1_total"]


def test_withdraw_plan_extractor_with_plans_spec_exclude_policies() -> None:
    """exclude_policies removes specified policies from allocation."""
    context = {
        "_rule_engine_result": {
            "requested_amount": 5000,
            "options": [
                {"policy_id": "POL001", "product_name": "A", "survival_fund_amt": 6000, "bonus_amt": 0, "loan_amt": 0, "refund_amt": 0},
                {"policy_id": "POL002", "product_name": "B", "survival_fund_amt": 4000, "bonus_amt": 0, "loan_amt": 0, "refund_amt": 0},
            ],
        },
    }
    card_args = {
        "plans": [
            {
                "title": "★ 推荐",
                "tag": "",
                "reason": "不动POL001",
                "channels": ["survival_fund"],
                "exclude_policies": ["POL001"],
            }
        ]
    }
    flat = withdraw_plan_extractor(context, card_args)

    assert flat["plan_1_hide"] is False
    labels = [p["label"] for p in flat["plan_1_policies"]]
    assert not any("POL001" in l for l in labels), "POL001 should be excluded"
    assert any("POL002" in l for l in labels), "POL002 should be allocated"


def test_withdraw_plan_extractor_with_plans_spec_invalid_channel_skipped() -> None:
    """Invalid channel IDs are silently skipped; remaining valid channels still allocated."""
    context = {
        "_rule_engine_result": {
            "requested_amount": 5000,
            "options": [
                {"policy_id": "P1", "survival_fund_amt": 8000, "bonus_amt": 0, "loan_amt": 0, "refund_amt": 0},
            ],
        },
    }
    card_args = {
        "plans": [
            {"title": "测试", "tag": "", "reason": "", "channels": ["bad_channel", "survival_fund"]},
        ]
    }
    flat = withdraw_plan_extractor(context, card_args)

    # valid channel (survival_fund) still allocates correctly
    assert flat["plan_1_hide"] is False
    labels = [p["label"] for p in flat["plan_1_policies"]]
    assert any("生存金" in l for l in labels)


def test_withdraw_plan_extractor_with_plans_spec_all_invalid_falls_back() -> None:
    """All-invalid channels in spec causes fallback to _generate_plans."""
    context = {
        "_rule_engine_result": {
            "requested_amount": 5000,
            "options": [
                {"policy_id": "P1", "survival_fund_amt": 8000, "bonus_amt": 0, "loan_amt": 0, "refund_amt": 0},
            ],
        },
    }
    card_args = {
        "plans": [
            {"title": "bad", "tag": "", "reason": "", "channels": ["nonexistent_channel"]},
        ]
    }
    flat = withdraw_plan_extractor(context, card_args)

    # Falls back to _generate_plans; Plan 1 should still render
    assert flat["plan_1_hide"] is False
    assert flat["plan_1_total"] != ""


def test_withdraw_plan_extractor_with_plans_spec_empty_list_falls_back() -> None:
    """Empty plans list falls back to _generate_plans."""
    context = {
        "_rule_engine_result": {
            "requested_amount": 5000,
            "options": [
                {"policy_id": "P1", "survival_fund_amt": 8000, "bonus_amt": 0, "loan_amt": 0, "refund_amt": 0},
            ],
        },
    }
    flat = withdraw_plan_extractor(context, {"plans": []})

    assert flat["plan_1_hide"] is False
    assert "★ 推荐" in flat["plan_1_title"] or "全部可用" in flat["plan_1_title"]


def test_withdraw_plan_extractor_with_plans_spec_insufficient_channels() -> None:
    """When channels can't meet target, actual_total (not target) is shown in plan total."""
    context = {
        "_rule_engine_result": {
            "requested_amount": 50000,
            "options": [
                {"policy_id": "P1", "survival_fund_amt": 3000, "bonus_amt": 2000, "loan_amt": 40000, "refund_amt": 0},
            ],
        },
    }
    card_args = {
        "plans": [
            {"title": "★ 零成本", "tag": "", "reason": "无法满足全额", "channels": ["survival_fund", "bonus"]},
        ]
    }
    flat = withdraw_plan_extractor(context, card_args)

    assert flat["plan_1_hide"] is False
    # Only 5000 available in those channels, not 50000
    assert "5,000" in flat["plan_1_total"]
    assert "50,000" not in flat["plan_1_total"]


def test_withdraw_plan_extractor_backward_compat_no_plans_key() -> None:
    """No plans key in card_args → _generate_plans used (backward compatible)."""
    context = {
        "_rule_engine_result": {
            "requested_amount": 5000,
            "options": [
                {"policy_id": "P1", "survival_fund_amt": 8000, "bonus_amt": 0, "loan_amt": 0, "refund_amt": 0},
            ],
        },
    }
    flat_with_args = withdraw_plan_extractor(context, None)
    flat_no_args = withdraw_plan_extractor(context, None)

    assert flat_with_args["plan_1_hide"] is False
    assert flat_no_args["plan_1_hide"] is False
    assert flat_with_args["plan_1_title"] == flat_no_args["plan_1_title"]


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
