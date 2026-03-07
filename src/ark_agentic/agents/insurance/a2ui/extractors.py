"""
保险 A2UI 卡片数据提取器

每个卡片类型一个提取函数：从 context 确定性计算业务数据，从 card_args 仅读取约定文案字段（字符串），
返回扁平 dict 供 core.a2ui.render_from_template 合并。
"""

from __future__ import annotations

import json
from typing import Any

# 与 rule_engine 一致
_LOAN_INTEREST_RATE = 0.05
_MAX_ITEMS = 2  # 与 template 固定 2 条明细一致


def _fmt(amount: float) -> str:
    return f"¥ {amount:,.2f}"


def _str_from_args(card_args: dict[str, Any] | None, key: str, default: str = "") -> str:
    if not card_args or key not in card_args:
        return default
    v = card_args[key]
    return str(v).strip() if v is not None else default


def withdraw_summary_extractor(context: dict[str, Any], card_args: dict[str, Any] | None) -> dict[str, Any]:
    """
    取款汇总卡片：从 context 读 _rule_engine_result，计算金额并展平为 item_1/item_2；
    从 card_args 仅读 advice_text_1、advice_text_2、plan_button_text、plan_action_query（文案）。
    """
    rule_data: Any = context.get("_rule_engine_result")
    if not rule_data:
        by_name = context.get("_tool_results_by_name") or {}
        rule_data = by_name.get("rule_engine")
    if not rule_data:
        raise ValueError("未找到 rule_engine 的数据，请先调用 rule_engine(action='list_options') 获取保单数据。")
    if isinstance(rule_data, str):
        rule_data = json.loads(rule_data)
    if not isinstance(rule_data, dict):
        raise ValueError("rule_engine 数据格式不符合预期。")

    options: list[dict[str, Any]] = rule_data.get("options", [])
    total_excl_loan = float(rule_data.get("total_available_excl_loan") or 0)
    total_incl_loan = float(rule_data.get("total_available_incl_loan") or 0)

    zero_cost_items: list[dict[str, str]] = []
    zero_cost_sum = 0.0
    for opt in options:
        name = opt.get("product_name") or opt.get("policy_id", "")
        survival = float(opt.get("survival_fund_amt") or 0)
        bonus = float(opt.get("bonus_amt") or 0)
        if survival > 0:
            zero_cost_items.append({"label": f"生存金({name})", "value": _fmt(survival)})
            zero_cost_sum += survival
        if bonus > 0:
            zero_cost_items.append({"label": f"红利({name})", "value": _fmt(bonus)})
            zero_cost_sum += bonus

    loan_items: list[dict[str, str]] = []
    loan_sum = 0.0
    for opt in options:
        loan = float(opt.get("loan_amt") or 0)
        if loan > 0:
            name = opt.get("product_name") or opt.get("policy_id", "")
            rate_pct = int(_LOAN_INTEREST_RATE * 100)
            loan_items.append({"label": f"{name} 可贷(年利率{rate_pct}%)", "value": _fmt(loan)})
            loan_sum += loan

    # 展平为 item_1 / item_2（不足补空串）
    def fill_items(items: list[dict[str, str]], prefix: str) -> dict[str, str]:
        out: dict[str, str] = {}
        for i in range(1, _MAX_ITEMS + 1):
            if i <= len(items):
                out[f"{prefix}_item_{i}_label"] = items[i - 1]["label"]
                out[f"{prefix}_item_{i}_value"] = items[i - 1]["value"]
            else:
                out[f"{prefix}_item_{i}_label"] = ""
                out[f"{prefix}_item_{i}_value"] = ""
        return out

    requested_raw = rule_data.get("requested_amount")
    if requested_raw is not None and isinstance(requested_raw, (int, float)):
        requested_amount_display = f"本次取款目标：{_fmt(float(requested_raw))}"
    else:
        requested_amount_display = "—"

    flat: dict[str, Any] = {
        "header_title": "目前可领取的总金额(含贷款)",
        "header_value": _fmt(total_incl_loan),
        "header_sub": f"不含贷款可领金额：{_fmt(total_excl_loan)}",
        "requested_amount_display": requested_amount_display,
        "section_marker": "|",
        "zero_cost_title": "零成本领取",
        "zero_cost_tag": "(不影响保障)",
        "zero_cost_total": f"合计：{_fmt(zero_cost_sum)}",
        **fill_items(zero_cost_items, "zero_cost"),
        "loan_title": "保单贷款",
        "loan_tag": "(需支付利息)",
        "loan_total": f"合计可贷：{_fmt(loan_sum)}",
        **fill_items(loan_items, "loan"),
        "advice_icon": "💡",
        "advice_title": "建议方案",
        "advice_text_1": _str_from_args(
            card_args, "advice_text_1", "• 建议优先领取零成本渠道（生存金、红利），不影响保障。"
        ),
        "advice_text_2": _str_from_args(
            card_args, "advice_text_2", "• 如需更多资金，可搭配保单贷款，年利率5%，保障不受影响。"
        ),
        "plan_button_text": _str_from_args(card_args, "plan_button_text", "获取最优方案"),
    }
    action_query = _str_from_args(card_args, "plan_action_query", flat["plan_button_text"])
    flat["plan_action_args"] = {"queryMsg": action_query}
    return flat
