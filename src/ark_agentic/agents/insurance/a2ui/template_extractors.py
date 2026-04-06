"""
card_type + template.json 专用：扁平 dict 提取器与方案生成。

渠道/分配公共逻辑见 withdraw_a2ui_utils。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ark_agentic.agents.insurance.tools.rule_engine import (
    LOAN_INTEREST_RATE as _LOAN_INTEREST_RATE,
)
from ark_agentic.core.a2ui.blocks import A2UIOutput

from .withdraw_a2ui_utils import (
    _ALL_CHANNELS,
    _VALID_CHANNELS,
    _allocate_to_target,
    _allocs_to_plan_parts,
    _channel_available,
    _fmt,
    _resolve_channel_filters,
)

logger = logging.getLogger(__name__)

_CHANNEL_DISPLAY_NAMES: dict[str, str] = {
    "survival_fund": "生存金",
    "bonus": "红利",
    "policy_loan": "贷款",
    "partial_withdrawal": "部分领取",
    "surrender": "退保",
}

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

_CAT_PRIORITY = ("zero_cost", "loan", "risk")


def withdraw_summary_extractor(context: dict[str, Any], card_args: dict[str, Any] | None) -> A2UIOutput:
    """
    取款汇总卡片：从 context 读 _rule_engine_result，按渠道分组计算金额；
    无数据的渠道卡片通过 hide flag 隐藏。

    card_args 支持:
      exclude_policies: list[str]  -- 排除指定保单
      exclude_channels: list[str]  -- 排除指定渠道
      include_channels: list[str]  -- 仅包含指定渠道（与 exclude_channels 互斥，优先）
    """
    rule_data: Any = context.get("_rule_engine_result")
    if not rule_data:
        raise ValueError("未找到 rule_engine 的数据，请先调用 rule_engine(action='list_options') 获取保单数据。")
    if isinstance(rule_data, str):
        rule_data = json.loads(rule_data)
    if not isinstance(rule_data, dict):
        raise ValueError("rule_engine 数据格式不符合预期。")

    options: list[dict[str, Any]] = rule_data.get("options", [])
    args = card_args or {}

    exclude_pids = set(args.get("exclude_policies") or [])
    if exclude_pids:
        options = [o for o in options if o.get("policy_id") not in exclude_pids]

    exclude_chs = _resolve_channel_filters(args)
    has_filters = bool(exclude_pids) or bool(exclude_chs)
    include_survival = "survival_fund" not in exclude_chs
    include_bonus = "bonus" not in exclude_chs
    include_loan = "policy_loan" not in exclude_chs

    def _refund_line_allowed(opt: dict[str, Any]) -> bool:
        amt = float(opt.get("refund_amt") or 0)
        if amt <= 0:
            return False
        is_wl = opt.get("product_type") == "whole_life"
        if is_wl:
            return "surrender" not in exclude_chs
        return "partial_withdrawal" not in exclude_chs

    zero_cost_items: list[dict[str, str]] = []
    zero_cost_sum = 0.0
    for opt in options:
        name = opt.get("product_name") or opt.get("policy_id", "")
        if include_survival:
            survival = float(opt.get("survival_fund_amt") or 0)
            if survival > 0:
                zero_cost_items.append({"label": f"生存金({name})", "value": _fmt(survival)})
                zero_cost_sum += survival
        if include_bonus:
            bonus = float(opt.get("bonus_amt") or 0)
            if bonus > 0:
                zero_cost_items.append({"label": f"红利({name})", "value": _fmt(bonus)})
                zero_cost_sum += bonus

    loan_items: list[dict[str, str]] = []
    loan_sum = 0.0
    if include_loan:
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
        if not _refund_line_allowed(opt):
            continue
        refund = float(opt.get("refund_amt") or 0)
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

    if has_filters:
        total_shown = zero_cost_sum + loan_sum + partial_surrender_sum
        excluded_names = [_CHANNEL_DISPLAY_NAMES[ch] for ch in exclude_chs if ch in _CHANNEL_DISPLAY_NAMES]
        header_title = "可取款总览"
        header_value = _fmt(total_shown)
        header_sub = f"已排除：{'、'.join(excluded_names)}" if excluded_names else ""
    else:
        total_incl_loan = float(rule_data.get("total_available_incl_loan") or 0)
        total_excl_loan_rule = float(rule_data.get("total_available_excl_loan") or 0)
        header_title = "目前可领取的总金额(含贷款)"
        header_value = _fmt(total_incl_loan)
        header_sub = f"不含贷款可领金额：{_fmt(total_excl_loan_rule)}"

    data = {
        "header_title": header_title,
        "header_value": header_value,
        "header_sub": header_sub,
        "requested_amount_display": requested_amount_display,
        "section_marker": "|",
        "zero_cost_hide": not zero_cost_items,
        "zero_cost_title": "零成本领取",
        "zero_cost_tag": "不影响保障",
        "zero_cost_total": f"合计：{_fmt(zero_cost_sum)}",
        "zero_cost_items": zero_cost_items,
        "loan_hide": not loan_items,
        "loan_title": "保单贷款",
        "loan_tag": "需支付利息",
        "loan_total": f"合计可贷：{_fmt(loan_sum)}",
        "loan_items": loan_items,
        "partial_surrender_hide": not partial_surrender_items,
        "partial_surrender_title": "部分领取/退保",
        "partial_surrender_tag": "保障有损失，不建议",
        "partial_surrender_total": f"合计：{_fmt(partial_surrender_sum)}",
        "partial_surrender_items": partial_surrender_items,
    }

    parts = [f"取款汇总: {header_title} {header_value}"]
    if zero_cost_sum > 0:
        parts.append(f"零成本 ¥{zero_cost_sum:,.2f}")
    if loan_sum > 0:
        parts.append(f"贷款 ¥{loan_sum:,.2f}")
    if partial_surrender_sum > 0:
        parts.append(f"退保 ¥{partial_surrender_sum:,.2f}")

    return A2UIOutput(template_data=data, llm_digest=" | ".join(parts))


def _category_total(options: list[dict[str, Any]], channels: tuple[str, ...]) -> float:
    return sum(_channel_available(o, ch) for o in options for ch in channels)


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
            "channels": channels,
            "allocs": allocs,
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


def _generate_plans(
    options: list[dict[str, Any]],
    target: float,
    exclude_channels: frozenset[str] | None = None,
) -> list[dict[str, Any]]:
    """以目标金额为中心生成最多 3 个方案。Plan 1 始终按优先级分配。

    exclude_channels 在所有层级生效：active channel 列表、cat_totals、备选方案。
    """
    _exclude = exclude_channels or frozenset()
    active = tuple(ch for ch in _ALL_CHANNELS if ch not in _exclude)
    cat_totals = {
        cat: _category_total(options, tuple(ch for ch in chs if ch not in _exclude))
        for cat, chs in _CAT_CHANNELS.items()
    }
    all_total = sum(cat_totals.values())
    if all_total <= 0:
        return []

    plans: list[dict[str, Any]] = []

    if target <= 0:
        allocs = _allocate_to_target(options, all_total, active)
        policies, buttons = _allocs_to_plan_parts(allocs)
        plans.append({"title": "全部可用渠道", "tag": "", "total": all_total,
                       "reason": "以下为所有可用的取款渠道及金额。",
                       "policies": policies, "buttons": buttons,
                       "channels": list(active), "allocs": allocs})
        return plans

    if all_total < target:
        allocs = _allocate_to_target(options, all_total, active)
        policies, buttons = _allocs_to_plan_parts(allocs)
        plans.append({
            "title": f"最大可取（不足目标 {_fmt(target)}）", "tag": "",
            "total": all_total,
            "reason": f"所有渠道合计 {_fmt(all_total)}，无法满足目标 {_fmt(target)}。",
            "policies": policies, "buttons": buttons,
            "channels": list(active), "allocs": allocs,
        })
        return plans

    allocs = _allocate_to_target(options, target, active)
    policies, buttons = _allocs_to_plan_parts(allocs)
    used_cats = _used_categories(allocs)

    if len(used_cats) == 1:
        name, tag, reason = _CAT_META[used_cats[0]]
    else:
        name = " + ".join(_CAT_META[c][0] for c in used_cats)
        tag = _combo_tag(used_cats)
        reason = _combo_reason(used_cats)

    used_channels = list(dict.fromkeys(ch for _, ch, _ in allocs))
    plans.append({
        "title": f"★ 推荐: {name}", "tag": tag, "total": target,
        "reason": reason, "policies": policies, "buttons": buttons,
        "channels": used_channels, "allocs": allocs,
    })

    if len(used_cats) == 1:
        for cat in _CAT_PRIORITY:
            if len(plans) >= 3:
                break
            if cat == used_cats[0]:
                continue
            cat_channels = tuple(ch for ch in _CAT_CHANNELS[cat] if ch not in _exclude)
            if not cat_channels or cat_totals[cat] < target:
                continue
            alt_allocs = _allocate_to_target(options, target, cat_channels)
            alt_policies, alt_buttons = _allocs_to_plan_parts(alt_allocs)
            alt_name, alt_tag, alt_reason = _CAT_META[cat]
            plans.append({
                "title": alt_name, "tag": alt_tag, "total": target,
                "reason": alt_reason, "policies": alt_policies, "buttons": alt_buttons,
                "channels": list(cat_channels), "allocs": alt_allocs,
            })

    return plans


def withdraw_plan_extractor(context: dict[str, Any], card_args: dict[str, Any] | None) -> A2UIOutput:
    """
    取款方案卡片：以目标金额为中心，生成最多 3 个方案。

    card_args 支持:
      exclude_policies: list[str]  -- 排除指定保单
      exclude_channels: list[str]  -- 排除指定渠道
      include_channels: list[str]  -- 仅包含指定渠道（与 exclude_channels 互斥，优先）
      plans: list[dict]            -- LLM 自定义方案规格（高级用法）
    """
    rule_data: Any = context.get("_rule_engine_result")
    if not rule_data:
        raise ValueError("未找到 rule_engine 数据，请先调用 rule_engine(action='list_options')。")
    if isinstance(rule_data, str):
        rule_data = json.loads(rule_data)
    if not isinstance(rule_data, dict):
        raise ValueError("rule_engine 数据格式不符合预期。")

    options: list[dict[str, Any]] = rule_data.get("options", [])
    args = card_args or {}
    requested_amount = float(rule_data.get("requested_amount") or 0)

    exclude_pids = set(args.get("exclude_policies") or [])
    if exclude_pids:
        options = [o for o in options if o.get("policy_id") not in exclude_pids]
    exclude_chs = _resolve_channel_filters(args)

    specs = args.get("plans")
    if specs and isinstance(specs, list):
        plans = _plans_from_spec(options, specs, requested_amount)
        if not plans:
            plans = _generate_plans(options, requested_amount, exclude_channels=exclude_chs)
    else:
        plans = _generate_plans(options, requested_amount, exclude_channels=exclude_chs)

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

    digest_parts: list[str] = []
    plan_allocations: list[dict[str, Any]] = []
    for plan in plans:
        allocs = plan.get("allocs", [])
        channels = plan.get("channels", [])
        title = plan["title"]
        total = plan["total"]
        detail = "; ".join(f"{pid}({ch}) ¥{amt:,.2f}" for pid, ch, amt in allocs)
        line = f"方案: {title} | channels: {channels} | 总额: ¥{total:,.2f}"
        if detail:
            line += f" | 明细: {detail}"
        digest_parts.append(line)
        plan_allocations.append({
            "title": title,
            "channels": channels,
            "allocations": [
                {"channel": ch, "policy_no": pid, "amount": amt}
                for pid, ch, amt in allocs
            ],
        })

    return A2UIOutput(
        template_data=data,
        llm_digest="\n".join(digest_parts),
        state_delta={"_plan_allocations": plan_allocations} if plan_allocations else None,
    )


def policy_detail_extractor(context: dict[str, Any], card_args: dict[str, Any] | None) -> A2UIOutput:
    """
    保单详情列表卡片：动态展示所有保单的四项金额明细，通过 List 组件渲染。
    数据源读 _rule_engine_result（由 rule_engine tool 的 state_delta 写入）。
    """
    rule_data: Any = context.get("_rule_engine_result")
    if not rule_data:
        raise ValueError("未找到保单数据，请先调用 rule_engine(action='list_options') 获取保单信息。")
    if isinstance(rule_data, str):
        rule_data = json.loads(rule_data)
    if not isinstance(rule_data, dict):
        raise ValueError("保单数据格式不符合预期。")

    options: list[dict[str, Any]] = rule_data.get("options", [])
    args = card_args or {}
    policy_ids = args.get("policy_ids")
    if policy_ids and isinstance(policy_ids, list):
        pid_set = set(policy_ids)
        options = [o for o in options if o.get("policy_id") in pid_set]
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

    data = {
        "section_marker": "|",
        "policies": [_build_policy_item(opt) for opt in options],
    }

    digest_lines = []
    for opt in options:
        name = opt.get("product_name") or opt.get("policy_id", "保单")
        pid = opt.get("policy_id", "")
        total = float(opt.get("available_amount") or 0)
        digest_lines.append(f"{name}({pid}) 合计¥{total:,.2f}")
    digest = "保单明细: " + "; ".join(digest_lines) if digest_lines else ""

    return A2UIOutput(template_data=data, llm_digest=digest)
