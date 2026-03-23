"""
取款相关 A2UI 工具：rule_engine options[] 渠道与分配。

与 template_extractors（card_type）及 components（blocks 管线）共用。
单一来源：_ALL_CHANNELS / _VALID_CHANNELS。
"""

from __future__ import annotations

from typing import Any

_ALL_CHANNELS = ("survival_fund", "bonus", "partial_withdrawal", "policy_loan", "surrender")

_VALID_CHANNELS: frozenset[str] = frozenset(_ALL_CHANNELS)

_OPTION_NAMES: dict[str, str] = {
    "survival_fund": "生存金领取",
    "bonus": "红利领取",
    "partial_withdrawal": "部分领取",
    "surrender": "退保",
    "policy_loan": "保单贷款",
}


def _fmt(amount: float) -> str:
    return f"¥ {amount:,.2f}"


def _resolve_channel_filters(args: dict[str, Any]) -> frozenset[str]:
    """Normalize include_channels / exclude_channels into a frozenset of excluded channel IDs."""
    include_chs = set(args.get("include_channels") or [])
    exclude_chs = set(args.get("exclude_channels") or [])
    if include_chs:
        exclude_chs = set(_ALL_CHANNELS) - include_chs
    return frozenset(exclude_chs)


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
