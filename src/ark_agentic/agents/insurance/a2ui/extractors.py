"""
保险 A2UI 卡片数据提取器

每个卡片类型一个提取函数：从 context 确定性计算业务数据，从 card_args 仅读取约定文案字段（字符串），
返回扁平 dict 供 core.a2ui.render_from_template 合并。
"""

from __future__ import annotations

import json
from typing import Any

from ark_agentic.agents.insurance.tools.rule_engine import (
    LOAN_INTEREST_RATE as _LOAN_INTEREST_RATE,
    PROCESSING_TIME as _PROCESSING_TIME,
)

_MAX_ITEMS = 2  # 与 template 固定 2 条明细一致

# option_type → (费用文案, 保障影响文案)
_OPTION_META: dict[str, tuple[str, str]] = {
    "survival_fund": ("无", "不影响保障"),
    "bonus": ("无", "不影响保障"),
    "partial_withdrawal": ("按保单年度收费", "现金价值减少，保额同步下降"),
    "surrender": ("无", "所有保障终止，退保后无法恢复"),
    "policy_loan": (
        f"年利率{int(_LOAN_INTEREST_RATE * 100)}%, 按日计息",
        "不影响保障（未按时还款可能导致保单中止）",
    ),
}

# option_type → 操作名称（用于按钮文案和 queryMsg）
_OPTION_NAMES: dict[str, str] = {
    "survival_fund": "生存金领取",
    "bonus": "红利领取",
    "partial_withdrawal": "部分领取",
    "surrender": "退保",
    "policy_loan": "保单贷款",
}


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
            loan_items.append({"label": f"{name}可贷(年利率{rate_pct}%)", "value": _fmt(loan)})
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
        "zero_cost_tag": " (不影响保障) ",
        "zero_cost_total": f"合计：{_fmt(zero_cost_sum)}",
        **fill_items(zero_cost_items, "zero_cost"),
        "loan_title": "保单贷款",
        "loan_tag": " (需支付利息) ",
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


def withdraw_plan_extractor(context: dict[str, Any], card_args: dict[str, Any] | None) -> dict[str, Any]:
    """
    取款方案卡片：rec/alt 两个方案均由 LLM 通过 card_args 指定。
    从 _rule_engine_result.options 匹配保单；费用/影响文案由 option_type 确定性生成。
    """
    rule_data: Any = context.get("_rule_engine_result")
    if not rule_data:
        by_name = context.get("_tool_results_by_name") or {}
        rule_data = by_name.get("rule_engine")
    if not rule_data:
        raise ValueError("未找到 rule_engine 数据，请先调用 rule_engine(action='list_options')。")
    if isinstance(rule_data, str):
        rule_data = json.loads(rule_data)
    if not isinstance(rule_data, dict):
        raise ValueError("rule_engine 数据格式不符合预期。")

    options: list[dict[str, Any]] = rule_data.get("options", [])
    args = card_args or {}

    def _best_option_type(opt: dict[str, Any]) -> str:
        """从 option 中推断收益最高的渠道类型（优先零成本）。"""
        if (opt.get("survival_fund_amt") or 0) > 0:
            return "survival_fund"
        if (opt.get("bonus_amt") or 0) > 0:
            return "bonus"
        if (opt.get("loan_amt") or 0) > 0:
            return "loan"
        return "partial_refund"

    def _option_amount(opt: dict[str, Any], otype: str) -> float | None:
        """根据渠道类型从 option 中读取对应金额。"""
        mapping = {
            "survival_fund": "survival_fund_amt",
            "bonus": "bonus_amt",
            "loan": "loan_amt",
            "partial_refund": "refund_amt",
            "surrender": "refund_amt",
        }
        key = mapping.get(otype)
        if key:
            v = opt.get(key)
            return float(v) if v is not None else None
        return None

    requested_amount: float | None = None
    if rule_data.get("requested_amount") is not None:
        try:
            requested_amount = float(rule_data["requested_amount"])
        except (TypeError, ValueError):
            pass

    def _resolve_option(policy_id_key: str, option_type_key: str, amount_key: str) -> dict[str, Any]:
        """从 card_args 解析某个方案，返回匹配的 option + amount；LLM 漏传时自动降级推断。"""
        pid = str(args.get(policy_id_key, "")).strip()
        otype = str(args.get(option_type_key, "")).strip()
        raw_amount = args.get(amount_key)

        # 按 policy_id 精确匹配，找不到则取第一条
        matched: dict[str, Any] | None = None
        if pid:
            matched = next((o for o in options if o.get("policy_id") == pid), None)
        if matched is None and options:
            matched = options[0]

        opt = matched or {}

        # 渠道类型降级推断
        if not otype and opt:
            otype = _best_option_type(opt)

        # 金额降级：优先 card_args，其次从 option 读取，最后用 requested_amount
        if raw_amount is None and opt:
            raw_amount = _option_amount(opt, otype)
        if raw_amount is None:
            raw_amount = requested_amount

        return {"option": opt, "option_type": otype, "amount": raw_amount}

    rec = _resolve_option("rec_policy_id", "rec_option_type", "rec_amount")
    alt = _resolve_option("alt_policy_id", "alt_option_type", "alt_amount")

    def _fmt_amount(v: Any) -> str:
        """返回纯数值字符串（不带单位）；优先使用 card_args 传入的文本。"""
        if v is None:
            return "—"
        try:
            return f"{float(v):,.2f}"
        except (TypeError, ValueError):
            return str(v)

    def _cost(otype: str) -> str:
        return _OPTION_META.get(otype, ("—", "—"))[0]

    def _impact(otype: str) -> str:
        return _OPTION_META.get(otype, ("—", "—"))[1]

    def _op_name(otype: str) -> str:
        return _OPTION_NAMES.get(otype, otype)

    def _policy_display(opt: dict[str, Any]) -> str:
        name = opt.get("product_name") or ""
        pid = opt.get("policy_id") or ""
        return f"{name}|{pid}" if name and pid else name or pid or "—"

    rec_opt = rec["option"]
    rec_type = rec["option_type"]
    alt_opt = alt["option"]
    alt_type = alt["option_type"]

    rec_op_name = _op_name(rec_type)
    alt_op_name = _op_name(alt_type)

    return {
        "page_title": _str_from_args(args, "page_title", "为您推荐的取款方案"),
        "section_marker": "| ",
        "label_policy": "关联保单: ",
        "label_time": "到账时间: ",
        "label_cost": "提取费用: ",
        "label_impact": "保障影响: ",
        "label_reason": "推荐理由: ",
        "amount_unit": "元",
        # 推荐方案
        "rec_title": _str_from_args(args, "rec_title", f"★ 推荐: {rec_op_name}"),
        "rec_amount": _fmt_amount(rec["amount"]),
        "rec_policy": _str_from_args(args, "rec_policy", _policy_display(rec_opt)),
        "rec_time": _str_from_args(args, "rec_time", _PROCESSING_TIME),
        "rec_cost": _str_from_args(args, "rec_cost", _cost(rec_type)),
        "rec_impact": _str_from_args(args, "rec_impact", _impact(rec_type)),
        "rec_reason": _str_from_args(args, "rec_reason", "零成本、无风险, 且不影响您的保障"),
        "rec_button_text": _str_from_args(args, "rec_button_text", f"办理{rec_op_name}"),
        "rec_action_args": {"queryMsg": _str_from_args(args, "rec_query_msg", f"我想办理{rec_op_name}")},
        # 备选方案
        "alt_title": _str_from_args(args, "alt_title", f"备选一: {alt_op_name}"),
        "alt_amount": _fmt_amount(alt["amount"]),
        "alt_policy": _str_from_args(args, "alt_policy", _policy_display(alt_opt)),
        "alt_time": _str_from_args(args, "alt_time", _PROCESSING_TIME),
        "alt_cost": _str_from_args(args, "alt_cost", _cost(alt_type)),
        "alt_impact": _str_from_args(args, "alt_impact", _impact(alt_type)),
        "alt_button_text": _str_from_args(args, "alt_button_text", f"办理{alt_op_name}"),
        "alt_action_args": {"queryMsg": _str_from_args(args, "alt_query_msg", f"我想办理{alt_op_name}")},
        "prompt_text": _str_from_args(args, "prompt_text", "请问您倾向于哪个方案？确认我可以为您办理。"),
    }


def policy_detail_extractor(context: dict[str, Any], card_args: dict[str, Any] | None) -> dict[str, Any]:
    """
    保单详情列表卡片：展示最多 3 张保单的四项金额明细。
    数据源优先读 _rule_engine_result，其次 _tool_results_by_name["policy_query"]。
    """
    rule_data: Any = context.get("_rule_engine_result")
    if not rule_data:
        by_name = context.get("_tool_results_by_name") or {}
        rule_data = by_name.get("rule_engine") or by_name.get("policy_query")
    if not rule_data:
        raise ValueError("未找到保单数据，请先调用 rule_engine(action='list_options') 获取保单信息。")
    if isinstance(rule_data, str):
        rule_data = json.loads(rule_data)
    if not isinstance(rule_data, dict):
        raise ValueError("保单数据格式不符合预期。")

    options: list[dict[str, Any]] = rule_data.get("options", [])
    # 按 available_amount 降序（rule_engine 已排序，此处保持健壮）
    options = sorted(options, key=lambda o: -float(o.get("available_amount") or 0))

    _MAX_POLICIES = 3
    args = card_args or {}

    flat: dict[str, Any] = {
        "page_title": _str_from_args(args, "page_title", "您的保单详情"),
        "section_marker": "|",
    }

    for i in range(1, _MAX_POLICIES + 1):
        prefix = f"p{i}"
        has_data = i <= len(options)
        # hide flag: True = 隐藏（无数据），False = 显示；p1 不控制 hide（始终显示）
        if i > 1:
            flat[f"{prefix}_hidden"] = not has_data
        if has_data:
            opt = options[i - 1]
            name = opt.get("product_name") or opt.get("policy_id", f"保单{i}")
            pid = opt.get("policy_id", "")
            year = opt.get("policy_year", "—")
            survival = float(opt.get("survival_fund_amt") or 0)
            bonus = float(opt.get("bonus_amt") or 0)
            loan = float(opt.get("loan_amt") or 0)
            refund = float(opt.get("refund_amt") or 0)
            total = float(opt.get("available_amount") or (survival + bonus + loan + refund))
            flat.update({
                f"{prefix}_title": name,
                f"{prefix}_subtitle": f"保单号: {pid}",
                f"{prefix}_year": f"保单年度: 第{year}年",
                f"{prefix}_survival_label": "生存金",
                f"{prefix}_survival_value": _fmt(survival),
                f"{prefix}_bonus_label": "红利",
                f"{prefix}_bonus_value": _fmt(bonus),
                f"{prefix}_loan_label": "可贷额度",
                f"{prefix}_loan_value": _fmt(loan),
                f"{prefix}_refund_label": "退保金",
                f"{prefix}_refund_value": _fmt(refund),
                f"{prefix}_total_label": "合计可用",
                f"{prefix}_total_value": _fmt(total),
            })
        else:
            # 空串保底，防止模板 path 解析报错
            for field in (
                "title", "subtitle", "year",
                "survival_label", "survival_value",
                "bonus_label", "bonus_value",
                "loan_label", "loan_value",
                "refund_label", "refund_value",
                "total_label", "total_value",
            ):
                flat[f"{prefix}_{field}"] = ""

    flat["prompt_text"] = _str_from_args(
        args, "prompt_text", "如需了解某张保单详情，请告诉我保单名称。"
    )
    return flat
