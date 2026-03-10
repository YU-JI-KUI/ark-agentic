"""
保险 A2UI 卡片数据提取器

每个卡片类型一个提取函数：从 context 确定性计算业务数据，从 card_args 仅读取约定文案字段（字符串），
返回扁平 dict 供 core.a2ui.render_from_template 合并。
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

from ark_agentic.agents.insurance.tools.rule_engine import (
    LOAN_INTEREST_RATE as _LOAN_INTEREST_RATE,
    PROCESSING_TIME as _PROCESSING_TIME,
)

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

    partial_surrender_items: list[dict[str, str]] = []
    partial_surrender_sum = 0.0
    for opt in options:
        refund = float(opt.get("refund_amt") or 0)
        if refund > 0:
            name = opt.get("product_name") or opt.get("policy_id", "")
            fee_rate = float(opt.get("refund_fee_rate") or 0)
            if fee_rate > 0:
                label = f"退保金({name}, 手续费{fee_rate:.0%})"
            else:
                label = f"退保金({name})"
            partial_surrender_items.append({"label": label, "value": _fmt(refund)})
            partial_surrender_sum += refund

    requested_raw = rule_data.get("requested_amount")
    if requested_raw is not None and isinstance(requested_raw, (int, float)):
        requested_amount_display = f"本次取款目标：{_fmt(float(requested_raw))}"
    else:
        requested_amount_display = "—"

    plan_button_text = _str_from_args(card_args, "plan_button_text", "获取最优方案")
    action_query = _str_from_args(card_args, "plan_action_query", plan_button_text)

    return {
        "header_title": "目前可领取的总金额(含贷款)",
        "header_value": _fmt(total_incl_loan),
        "header_sub": f"不含贷款可领金额：{_fmt(total_excl_loan)}",
        "requested_amount_display": requested_amount_display,
        "section_marker": "|",
        "zero_cost_title": "零成本领取",
        "zero_cost_tag": "不影响保障",
        "zero_cost_total": f"合计：{_fmt(zero_cost_sum)}",
        "zero_cost_items": zero_cost_items,
        "loan_title": "保单贷款",
        "loan_tag": "需支付利息",
        "loan_total": f"合计可贷：{_fmt(loan_sum)}",
        "loan_items": loan_items,
        "partial_surrender_title": "部分领取/退保",
        "partial_surrender_tag": "保障有损失，不建议",
        "partial_surrender_total": f"合计：{_fmt(partial_surrender_sum)}",
        "partial_surrender_items": partial_surrender_items,
        "advice_icon": "💡",
        "advice_title": "建议方案",
        "advice_text_1": _str_from_args(
            card_args, "advice_text_1", "• 建议优先领取零成本渠道（生存金、红利），不影响保障。"
        ),
        "advice_text_2": _str_from_args(
            card_args, "advice_text_2", "• 如需更多资金，可搭配保单贷款，年利率5%，保障不受影响。"
        ),
        "advice_text_3": _str_from_args(
            card_args, "advice_text_3", "• 部分领取或退保会导致保障减少或终止，不建议优先选择。"
        ),
        "plan_button_text": plan_button_text,
        "plan_action_args": {"queryMsg": action_query},
    }


_ALL_CHANNELS = ("survival_fund", "bonus", "partial_withdrawal", "policy_loan", "surrender")

_CAT_CHANNELS: dict[str, tuple[str, ...]] = {
    "zero_cost": ("survival_fund", "bonus"),
    "loan": ("policy_loan",),
    "risk": ("partial_withdrawal", "surrender"),
}

_CAT_META: dict[str, tuple[str, str, str]] = {
    "zero_cost": ("零成本领取", "(不影响保障)", "零成本、无风险，不影响您的保障"),
    "loan": ("保单贷款", "(需支付利息)", "保障不受影响，适合短期周转"),
    "risk": ("部分领取/退保", "(保障有损失，不建议)", "可能导致保障减少或终止"),
}

_BTN_TEXT: dict[str, str] = {
    "survival_fund": "领取生存金",
    "bonus": "领取红利",
    "policy_loan": "办理保单贷款",
    "partial_withdrawal": "办理部分领取",
    "surrender": "办理退保",
}

_CHANNEL_LABELS: dict[str, str] = {
    "survival_fund": "生存金",
    "bonus": "红利",
    "policy_loan": "保单贷款",
    "partial_withdrawal": "部分领取",
    "surrender": "退保",
}


def _channel_available(opt: dict[str, Any], channel: str) -> float:
    """读取单张保单某渠道的可用金额。"""
    if channel == "survival_fund":
        return float(opt.get("survival_fund_amt") or 0)
    if channel == "bonus":
        return float(opt.get("bonus_amt") or 0)
    if channel == "policy_loan":
        return float(opt.get("loan_amt") or 0)
    is_whole_life = opt.get("product_type") == "whole_life"
    if channel == "partial_withdrawal":
        return 0.0 if is_whole_life else float(opt.get("refund_amt") or 0)
    if channel == "surrender":
        return float(opt.get("refund_amt") or 0) if is_whole_life else 0.0
    return 0.0


def _category_total(options: list[dict[str, Any]], channels: tuple[str, ...]) -> float:
    return sum(_channel_available(o, ch) for o in options for ch in channels)


def _allocate_to_target(
    options: list[dict[str, Any]], target: float, channels: tuple[str, ...] | list[str],
) -> list[tuple[str, str, float]]:
    """按优先级将 target 分配到指定渠道，返回 [(policy_id, channel, allocated_amt)]。"""
    remaining = target
    result: list[tuple[str, str, float]] = []
    for ch in channels:
        if remaining <= 0:
            break
        for opt in options:
            if remaining <= 0:
                break
            avail = _channel_available(opt, ch)
            if avail <= 0:
                continue
            take = min(remaining, avail)
            result.append((opt.get("policy_id", ""), ch, take))
            remaining -= take
    return result


def _build_query_msg(action_name: str, entries: list[tuple[str, float]]) -> str:
    """生成 queryMsg，格式：'办理生存金领取，POL001，12000.00，POL002，5200.00'"""
    if not entries:
        return f"办理{action_name}"
    parts = [f"办理{action_name}"]
    for pid, amt in entries:
        parts.extend([pid, f"{amt:.2f}"])
    return "，".join(parts)


def _allocs_to_plan_parts(
    allocs: list[tuple[str, str, float]],
) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    """将分配结果转换为 (policies_display, buttons)。"""
    policies: list[dict[str, str]] = []
    by_channel: dict[str, list[tuple[str, float]]] = {}
    for pid, ch, amt in allocs:
        label = _CHANNEL_LABELS.get(ch, ch)
        policies.append({"label": f"{pid} {label}", "value": _fmt(amt)})
        by_channel.setdefault(ch, []).append((pid, amt))

    buttons: list[dict[str, Any]] = []
    for ch in _ALL_CHANNELS:
        entries = by_channel.get(ch)
        if not entries:
            continue
        buttons.append({
            "text": _BTN_TEXT.get(ch, ch),
            "action": {"queryMsg": _build_query_msg(_OPTION_NAMES.get(ch, ch), entries)},
        })
    return policies, buttons


_CAT_PRIORITY = ("zero_cost", "loan", "risk")

_VALID_CHANNELS: frozenset[str] = frozenset(_ALL_CHANNELS)


def _plans_from_spec(
    options: list[dict[str, Any]],
    specs: list[dict[str, Any]],
    default_target: float,
) -> list[dict[str, Any]]:
    """按 LLM 提供的方案规格计算分配。

    每个 spec 指定渠道顺序（channels）、目标金额（target）、排除保单（exclude_policies）和文案。
    extractor 只负责按规格调用 _allocate_to_target 并计算具体金额。
    """
    plans: list[dict[str, Any]] = []
    for spec in specs[:3]:
        raw_channels: list[str] = spec.get("channels") or list(_ALL_CHANNELS)
        channels = [ch for ch in raw_channels if ch in _VALID_CHANNELS]
        if len(channels) < len(raw_channels):
            invalid = [ch for ch in raw_channels if ch not in _VALID_CHANNELS]
            logger.warning("_plans_from_spec: 未知渠道ID已跳过: %s", invalid)
        if not channels:
            logger.warning("_plans_from_spec: 方案 %r 无有效渠道，跳过", spec.get("title", ""))
            continue

        exclude_channels: set[str] = set(spec.get("exclude_channels") or [])
        exclude_pids: set[str] = set(spec.get("exclude_policies") or [])
        filtered = [o for o in options if o.get("policy_id") not in exclude_pids] if exclude_pids else options

        target_raw = spec.get("target")
        if target_raw:
            target = float(target_raw)
        elif default_target > 0:
            target = default_target
        else:
            target = sum(_channel_available(o, ch) for o in filtered for ch in channels)

        allocs = _allocate_to_target(filtered, target, channels)
        actual_total = sum(a for _, _, a in allocs)

        # Auto-fill: if preferred channels can't meet target, extend with remaining
        # channels (in _ALL_CHANNELS priority order), respecting exclude_channels.
        if actual_total < target and target > 0:
            channels_set = set(channels)
            fill_channels = [
                ch for ch in _ALL_CHANNELS
                if ch not in channels_set and ch not in exclude_channels
            ]
            if fill_channels:
                extra = _allocate_to_target(filtered, target - actual_total, fill_channels)
                allocs = allocs + extra
                actual_total = sum(a for _, _, a in allocs)

        policies, buttons = _allocs_to_plan_parts(allocs)
        plans.append({
            "title": spec.get("title") or "",
            "tag": spec.get("tag") or "",
            "total": actual_total,
            "reason": spec.get("reason") or "",
            "policies": policies,
            "buttons": buttons,
        })
    return plans


def _used_categories(allocs: list[tuple[str, str, float]]) -> list[str]:
    """从分配结果中提取实际使用的类别（保持优先级顺序）。"""
    used: set[str] = set()
    for _, ch, _ in allocs:
        for cat, chs in _CAT_CHANNELS.items():
            if ch in chs:
                used.add(cat)
                break
    return [c for c in _CAT_PRIORITY if c in used]


def _combo_tag(cats: list[str]) -> str:
    """根据类别组合生成标签。"""
    has_loan = "loan" in cats
    has_risk = "risk" in cats
    if has_loan and has_risk:
        return "(部分需付利息且保障有损失)"
    if has_loan:
        return "(部分需付利息)"
    if has_risk:
        return "(部分保障有损失)"
    return "(不影响保障)"


def _combo_reason(cats: list[str]) -> str:
    """根据类别组合生成推荐理由。"""
    if len(cats) == 1:
        return _CAT_META[cats[0]][2]
    return "优先使用零成本渠道；不足部分依次搭配其他渠道补足。"


def _generate_plans(options: list[dict[str, Any]], target: float) -> list[dict[str, Any]]:
    """以目标金额为中心生成最多 3 个方案。Plan 1 始终按优先级分配。"""
    cat_totals = {cat: _category_total(options, chs) for cat, chs in _CAT_CHANNELS.items()}
    all_total = sum(cat_totals.values())
    if all_total <= 0:
        return []

    plans: list[dict[str, Any]] = []

    if target <= 0:
        allocs = _allocate_to_target(options, all_total, _ALL_CHANNELS)
        policies, buttons = _allocs_to_plan_parts(allocs)
        plans.append({"title": "全部可用渠道", "tag": "", "total": all_total,
                       "reason": "以下为所有可用的取款渠道及金额。",
                       "policies": policies, "buttons": buttons})
        return plans

    if all_total < target:
        allocs = _allocate_to_target(options, all_total, _ALL_CHANNELS)
        policies, buttons = _allocs_to_plan_parts(allocs)
        plans.append({
            "title": f"最大可取（不足目标 {_fmt(target)}）", "tag": "",
            "total": all_total,
            "reason": f"所有渠道合计 {_fmt(all_total)}，无法满足目标 {_fmt(target)}。",
            "policies": policies, "buttons": buttons,
        })
        return plans

    # Plan 1: 始终按优先级分配 (zero_cost -> loan -> risk)
    allocs = _allocate_to_target(options, target, _ALL_CHANNELS)
    policies, buttons = _allocs_to_plan_parts(allocs)
    used_cats = _used_categories(allocs)

    if len(used_cats) == 1:
        name, tag, reason = _CAT_META[used_cats[0]]
    else:
        name = " + ".join(_CAT_META[c][0] for c in used_cats)
        tag = _combo_tag(used_cats)
        reason = _combo_reason(used_cats)

    plans.append({
        "title": f"★ 推荐: {name}", "tag": tag, "total": target,
        "reason": reason, "policies": policies, "buttons": buttons,
    })

    # 备选方案：仅当 Plan 1 是单类时，添加其他能独立满足的单类
    if len(used_cats) == 1:
        for cat in _CAT_PRIORITY:
            if len(plans) >= 3:
                break
            if cat == used_cats[0]:
                continue
            if cat_totals[cat] < target:
                continue
            alt_allocs = _allocate_to_target(options, target, _CAT_CHANNELS[cat])
            alt_policies, alt_buttons = _allocs_to_plan_parts(alt_allocs)
            alt_name, alt_tag, alt_reason = _CAT_META[cat]
            plans.append({
                "title": alt_name, "tag": alt_tag, "total": target,
                "reason": alt_reason, "policies": alt_policies, "buttons": alt_buttons,
            })

    return plans


def withdraw_plan_extractor(context: dict[str, Any], card_args: dict[str, Any] | None) -> dict[str, Any]:
    """
    取款方案卡片：以目标金额为中心，生成最多 3 个方案。
    每个方案分配恰好目标金额（或最大可取），关联保单列表 + 2x2 按钮网格。
    Plan 1 按钮 primary，Plan 2/3 按钮 secondary（由 template 静态指定）。
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
    requested_amount = float(rule_data.get("requested_amount") or 0)

    specs = args.get("plans")
    if specs and isinstance(specs, list):
        plans = _plans_from_spec(options, specs, requested_amount)
        if not plans:
            plans = _generate_plans(options, requested_amount)
    else:
        plans = _generate_plans(options, requested_amount)

    data: dict[str, Any] = {
        "section_marker": "|",
    }

    for i in range(3):
        p = f"plan_{i + 1}_"
        if i < len(plans):
            plan = plans[i]
            tag_str = plan.get("tag", "") or ""
            data[f"{p}hide"] = False
            data[f"{p}title"] = plan["title"]
            data[f"{p}tag"] = tag_str
            data[f"{p}tag_hide"] = not tag_str.strip()
            data[f"{p}total"] = f"合计：{_fmt(plan['total'])}"
            data[f"{p}reason"] = plan["reason"]
            data[f"{p}policies"] = plan["policies"]
            btns = plan.get("buttons", [])
            for j in range(4):
                bn = j + 1
                if j < len(btns):
                    data[f"{p}btn_{bn}_hide"] = False
                    data[f"{p}btn_{bn}_text"] = btns[j]["text"]
                    data[f"{p}btn_{bn}_action"] = btns[j]["action"]
                else:
                    data[f"{p}btn_{bn}_hide"] = True
                    data[f"{p}btn_{bn}_text"] = ""
                    data[f"{p}btn_{bn}_action"] = {"queryMsg": ""}
        else:
            data[f"{p}hide"] = True
            data[f"{p}title"] = ""
            data[f"{p}tag"] = ""
            data[f"{p}tag_hide"] = True
            data[f"{p}total"] = ""
            data[f"{p}reason"] = ""
            data[f"{p}policies"] = []
            for bn in range(1, 5):
                data[f"{p}btn_{bn}_hide"] = True
                data[f"{p}btn_{bn}_text"] = ""
                data[f"{p}btn_{bn}_action"] = {"queryMsg": ""}

    return data


def policy_detail_extractor(context: dict[str, Any], card_args: dict[str, Any] | None) -> dict[str, Any]:
    """
    保单详情列表卡片：动态展示所有保单的四项金额明细，通过 List 组件渲染。
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
    options = sorted(options, key=lambda o: -float(o.get("available_amount") or 0))

    def _build_policy_item(opt: dict[str, Any]) -> dict[str, Any]:
        name = opt.get("product_name") or opt.get("policy_id", "保单")
        pid = opt.get("policy_id", "")
        year = opt.get("policy_year", "—")
        survival = float(opt.get("survival_fund_amt") or 0)
        bonus = float(opt.get("bonus_amt") or 0)
        loan = float(opt.get("loan_amt") or 0)
        refund = float(opt.get("refund_amt") or 0)
        total = float(opt.get("available_amount") or (survival + bonus + loan + refund))
        return {
            "title": name,
            "subtitle": f"保单号: {pid}",
            "year": f"保单年度: 第{year}年",
            "survival_label": "生存金",
            "survival_value": _fmt(survival),
            "bonus_label": "红利",
            "bonus_value": _fmt(bonus),
            "loan_label": "可贷额度",
            "loan_value": _fmt(loan),
            "refund_label": "退保金",
            "refund_value": _fmt(refund),
            "total_label": "合计可用",
            "total_value": _fmt(total),
        }

    return {
        "section_marker": "|",
        "policies": [_build_policy_item(opt) for opt in options],
    }
