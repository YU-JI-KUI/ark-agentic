"""
Insurance agent component builders (coarse-grained, business-aware).

Each component: (data, id_gen, raw_data) -> A2UIOutput.
Components read raw_data, perform business logic, and return:
  - components  -> UI payload for frontend
  - llm_digest  -> concise text for LLM conversation context
  - state_delta -> session state for downstream tool auto-fill

Styles strictly match the 3 template.json files in templates/.

Theme is injected via ``create_insurance_components(theme)`` closure factory.
The module-level ``INSURANCE_COMPONENTS`` dict uses the default theme for
backward compatibility.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ark_agentic.core.a2ui.blocks import (
    _comp,
    _text,
    A2UIOutput,
    IdGen,
)
from ark_agentic.core.a2ui.theme import A2UITheme

from .withdraw_a2ui_utils import (
    _ALL_CHANNELS,
    _CHANNEL_LABELS,
    _allocate_to_target,
    _allocs_to_plan_parts,
    _channel_available,
    _fmt,
)

logger = logging.getLogger(__name__)

SECTION_TYPES: tuple[str, ...] = (
    "zero_cost",
    "survival_fund",
    "bonus",
    "loan",
    "partial_withdrawal",
    "surrender",
)
"""WithdrawSummary 板块枚举；与 `_section_presets` 字面量对齐。"""

CHANNEL_TYPES: tuple[str, ...] = _ALL_CHANNELS
"""取款渠道枚举；单一事实源来自 withdraw_a2ui_utils._ALL_CHANNELS。"""


def _parse_options(raw_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract options list from raw_data, with resilient parsing."""
    options = raw_data.get("options")
    if options is None:
        return []
    if isinstance(options, str):
        try:
            options = json.loads(options)
        except json.JSONDecodeError:
            return []
    return options if isinstance(options, list) else []


def create_insurance_components(theme: A2UITheme | None = None) -> dict[str, Any]:
    """Factory that returns component builders with *theme* bound via closure."""
    t = theme or A2UITheme()

    # -- Section presets (colors derived from theme) --

    _section_presets: dict[str, dict[str, Any]] = {
        "zero_cost": {
            "channels": ("survival_fund", "bonus"),
            "title": "零成本领取",
            "tag": "不影响保障",
            "tag_color": "#6cb585",
            "line_color": t.accent,
            "total_color": t.accent,
        },
        "survival_fund": {
            "channels": ("survival_fund",),
            "title": "生存金",
            "tag": "不影响保障",
            "tag_color": "#6cb585",
            "line_color": t.accent,
            "total_color": t.accent,
        },
        "bonus": {
            "channels": ("bonus",),
            "title": "红利",
            "tag": "不影响保障",
            "tag_color": "#6cb585",
            "line_color": t.accent,
            "total_color": t.accent,
        },
        "loan": {
            "channels": ("policy_loan",),
            "title": "保单贷款",
            "tag": "需支付利息",
            "tag_color": "#FF8800",
            "line_color": t.accent,
            "total_color": t.accent,
        },
        "partial_withdrawal": {
            "channels": ("partial_withdrawal",),
            "title": "部分领取",
            "tag": "保额会降低",
            "tag_color": "#FA8C16",
            "line_color": t.accent,
            "total_color": t.hint_color,
        },
        "surrender": {
            "channels": ("surrender",),
            "title": "退保",
            "tag": "保障终止，不建议",
            "tag_color": "#CC6600",
            "line_color": "#CC6600",
            "total_color": t.hint_color,
        },
    }

    assert tuple(_section_presets.keys()) == SECTION_TYPES, (
        "_section_presets 的键顺序必须与 SECTION_TYPES 常量保持一致"
    )

    # -- Title/tag derivation (single source of truth: actual_channels) --

    _SINGLE_CHANNEL_LABELS: dict[str, tuple[str, str, str]] = {
        # channel -> (title, tag, tag_color)
        "survival_fund":      ("生存金领取", "不影响保障", "#6cb585"),
        "bonus":              ("红利领取",   "不影响保障", "#6cb585"),
        "policy_loan":        ("保单贷款",   "需支付利息", "#FF8800"),
        "partial_withdrawal": ("部分领取",   "保额会降低", "#FA8C16"),
        "surrender":          ("退保",       "保障终止",   "#CC6600"),
    }

    def _derive_title_tag(
        actual_channels: list[str],
        is_recommended: bool,
    ) -> tuple[str, str, str]:
        """Derive (title, tag, tag_color) from the channels actually allocated.

        This is the single source of truth — LLM-supplied title/tag are ignored
        to prevent visual/allocation drift (e.g., title says "含贷款" but no loan
        was allocated because target was met by an earlier channel).
        """
        if not actual_channels:
            return ("无可用方案", "", t.hint_color)

        if len(actual_channels) == 1:
            title, tag, tag_color = _SINGLE_CHANNEL_LABELS[actual_channels[0]]
            if is_recommended:
                title = f"★ 推荐: {title}"
            return (title, tag, tag_color)

        chs = set(actual_channels)
        zero_only = chs <= {"survival_fund", "bonus"}
        has_loan = "policy_loan" in chs
        has_surrender = "surrender" in chs
        has_partial = "partial_withdrawal" in chs

        if zero_only:
            title = "★ 推荐: 零成本领取" if is_recommended else "零成本领取"
            return (title, "不影响保障", "#6cb585")
        if has_surrender:
            title = "★ 推荐: 含退保方案" if is_recommended else "含退保方案"
            return (title, "保障终止", "#CC6600")
        if has_loan:
            title = "★ 推荐: 含保单贷款方案" if is_recommended else "含保单贷款方案"
            return (title, "需支付利息", "#FF8800")
        if has_partial:
            title = "★ 推荐: 组合领取方案" if is_recommended else "组合领取方案"
            return (title, "保额会降低", "#FA8C16")
        title = "★ 推荐: 组合方案" if is_recommended else "组合方案"
        return (title, "", t.hint_color)

    # -- Shared helper --

    def _item_rows(
        items: list[dict[str, str]],
        g: IdGen,
        *,
        gap: int = 8,
    ) -> tuple[str, list[dict[str, Any]]]:
        """Unroll label/value items into Column > Row > Text(literalString)."""
        col_id = g("column")
        row_ids: list[str] = []
        comps: list[dict[str, Any]] = []
        for item in items:
            row_id = g("row")
            label_id, val_id = g("text"), g("text")
            comps.append(_text(label_id, item["label"], color=t.body_color, fontSize="14px"))
            comps.append(_text(val_id, item["value"], color=t.body_color, fontSize="14px"))
            comps.append(_comp(row_id, "Row", {
                "width": 100,
                "distribution": "spaceBetween",
                "children": {"explicitList": [label_id, val_id]},
            }))
            row_ids.append(row_id)
        comps.append(_comp(col_id, "Column", {
            "gap": gap,
            "children": {"explicitList": row_ids},
        }))
        return col_id, comps

    # -- Component builders --

    def build_withdraw_summary_header(
        data: dict[str, Any],
        g: IdGen,
        raw_data: dict[str, Any],
    ) -> A2UIOutput:
        """Header card for withdraw summary."""
        options = _parse_options(raw_data)
        sections = data.get("sections", ["zero_cost", "loan", "partial_withdrawal", "surrender"])
        exclude_pids = set(data.get("exclude_policies") or [])
        if exclude_pids:
            options = [o for o in options if o.get("policy_id") not in exclude_pids]

        total = 0.0
        for sec_name in sections:
            preset = _section_presets.get(sec_name)
            if not preset:
                continue
            for ch in preset["channels"]:
                for opt in options:
                    total += _channel_available(opt, ch)

        requested_raw = raw_data.get("requested_amount")
        if requested_raw is not None and isinstance(requested_raw, (int, float)):
            requested_display = f"本次取款目标：{_fmt(float(requested_raw))}"
        else:
            requested_display = ""

        has_loan_section = "loan" in sections
        loan_total = (
            sum(_channel_available(opt, "policy_loan") for opt in options)
            if has_loan_section else 0.0
        )
        total_excl_loan = total - loan_total

        card_id, col_id = g("card"), g("column")
        title_id, value_id = g("text"), g("text")

        col_children = [title_id, value_id]
        comps: list[dict[str, Any]] = []

        header_title = "目前可领取的总金额(含贷款)" if has_loan_section else "目前可领取的总金额"
        comps.append(_text(title_id, header_title,
                           color=t.title_color, fontSize="16px", bold=True))
        comps.append(_text(value_id, _fmt(total),
                           color=t.accent, fontSize="24px", bold=True))

        if has_loan_section and total > 0:
            sub_id = g("text")
            col_children.append(sub_id)
            comps.append(_text(sub_id, f"不含贷款可领金额：{_fmt(total_excl_loan)}",
                               color=t.hint_color, fontSize="12px"))

        if requested_display:
            req_id = g("text")
            col_children.append(req_id)
            comps.append(_text(req_id, requested_display, color=t.note_color, fontSize="12px"))

        col = _comp(col_id, "Column", {
            "alignment": "center",
            "gap": t.header_gap,
            "children": {"explicitList": col_children},
        })
        card = _comp(card_id, "Card", {
            "width": 100,
            "backgroundColor": t.card_bg,
            "borderRadius": t.card_radius,
            "padding": t.header_padding,
            "children": {"explicitList": [col_id]},
        })

        loan_flag = "true" if has_loan_section else "false"
        digest = (
            f"[卡片:总览/合计 total={total:.2f} loan_included={loan_flag}]"
            f" 总可领 ¥{total:,.2f}"
        )
        if has_loan_section and total > 0:
            digest += f" · 不含贷款 ¥{total_excl_loan:,.2f}"

        return A2UIOutput(components=[card, col] + comps, llm_digest=digest)

    def build_withdraw_summary_section(
        data: dict[str, Any],
        g: IdGen,
        raw_data: dict[str, Any],
    ) -> A2UIOutput:
        """Section card for withdraw summary."""
        section_name = data.get("section_name")
        if section_name and section_name in _section_presets:
            preset = _section_presets[section_name]
            channels = preset["channels"]
            title = preset["title"]
            tag = preset["tag"]
            tag_color = preset["tag_color"]
            line_color = preset.get("line_color", t.accent)
            total_color = preset.get("total_color", t.accent)
        else:
            channels = tuple(data.get("channels", []))
            title = data.get("title", "")
            tag = data.get("tag", "")
            tag_color = data.get("tag_color", t.hint_color)
            line_color = data.get("line_color", t.accent)
            total_color = data.get("total_color", t.accent)
            section_name = "_".join(channels) if channels else "custom"

        options = _parse_options(raw_data)
        exclude_pids = set(data.get("exclude_policies") or [])
        if exclude_pids:
            options = [o for o in options if o.get("policy_id") not in exclude_pids]

        items: list[dict[str, str]] = []
        total_sum = 0.0
        for ch in channels:
            for opt in options:
                amt = _channel_available(opt, ch)
                if amt <= 0:
                    continue
                name = opt.get("product_name") or opt.get("policy_id", "")
                ch_label = _CHANNEL_LABELS.get(ch, ch)
                items.append({"label": f"{ch_label}({name})", "value": _fmt(amt)})
                total_sum += amt

        if not items:
            return A2UIOutput()

        card_id, col_id = g("card"), g("column")
        row_id = g("row")
        line_id, title_id, tag_id = g("line"), g("text"), g("tag")
        total_id, div_id = g("text"), g("divider")

        comps: list[dict[str, Any]] = []

        comps.append(_comp(line_id, "Line", {
            "backgroundColor": line_color,
            "minWidth": "3px",
            "minHeight": "16px",
            "borderRadius": "small",
        }))
        comps.append(_text(title_id, title, color=t.title_color, fontSize="16px", bold=True))
        comps.append(_comp(tag_id, "Tag", {
            "text": {"literalString": tag},
            "color": tag_color,
            "size": "small",
        }))
        comps.append(_comp(row_id, "Row", {
            "alignment": "middle",
            "gap": t.header_gap,
            "children": {"explicitList": [line_id, title_id, tag_id]},
        }))

        comps.append(_text(total_id, f"合计：{_fmt(total_sum)}", color=total_color, fontSize="16px", bold=True))

        comps.append(_comp(div_id, "Divider", {"borderColor": t.divider_color, "hairline": True}))

        items_col_id, item_comps = _item_rows(items, g)
        comps.extend(item_comps)

        col = _comp(col_id, "Column", {
            "gap": t.section_gap,
            "children": {"explicitList": [row_id, total_id, div_id, items_col_id]},
        })
        card = _comp(card_id, "Card", {
            "width": 100,
            "backgroundColor": t.card_bg,
            "borderRadius": t.card_radius,
            "padding": t.card_padding,
            "children": {"explicitList": [col_id]},
        })

        detail = " · ".join(f"{item['label']} {item['value']}" for item in items)
        digest = (
            f"[卡片:总览/板块 name={section_name} total={total_sum:.2f}]"
            f" {title} · {detail}"
        )

        return A2UIOutput(components=[card, col] + comps, llm_digest=digest)

    def build_withdraw_plan_card(
        data: dict[str, Any],
        g: IdGen,
        raw_data: dict[str, Any],
    ) -> A2UIOutput:
        """Plan card for withdraw plan."""
        options = _parse_options(raw_data)
        exclude_pids = set(data.get("exclude_policies") or [])
        if exclude_pids:
            options = [o for o in options if o.get("policy_id") not in exclude_pids]

        channels: list[str] = data.get("channels") or list(_ALL_CHANNELS)
        target = float(data.get("target") or 0)
        is_recommended = bool(data.get("is_recommended", False))
        reason = data.get("reason", "")

        if target <= 0:
            target = sum(_channel_available(o, ch) for o in options for ch in channels)

        allocs = _allocate_to_target(options, target, channels)
        actual_total = sum(a for _, _, a in allocs)
        policies, buttons = _allocs_to_plan_parts(allocs)

        actual_channels = list(dict.fromkeys(ch for _, ch, _ in allocs))
        title, tag_text, tag_color_derived = _derive_title_tag(actual_channels, is_recommended)

        card_id, col_id = g("card"), g("column")
        row_id = g("row")
        marker_id, title_id = g("text"), g("text")
        total_id = g("text")

        col_children: list[str] = [row_id]
        comps: list[dict[str, Any]] = []

        comps.append(_text(marker_id, "|", color=t.accent, fontSize="16px", bold=True))
        comps.append(_text(title_id, title, color=t.title_color, fontSize="16px", bold=True))
        comps.append(_comp(row_id, "Row", {
            "alignment": "middle",
            "gap": t.header_gap,
            "children": {"explicitList": [marker_id, title_id]},
        }))

        if tag_text:
            tag_tid = g("text")
            col_children.append(tag_tid)
            comps.append(_text(tag_tid, tag_text, color=tag_color_derived, fontSize="12px"))

        col_children.append(total_id)
        comps.append(_text(total_id, f"合计：{_fmt(actual_total)}", color=t.accent, fontSize="16px", bold=True))

        if reason:
            reason_id = g("text")
            col_children.append(reason_id)
            comps.append(_text(reason_id, reason, color=t.hint_color, fontSize="13px"))

        div_id = g("divider")
        col_children.append(div_id)
        comps.append(_comp(div_id, "Divider", {"borderColor": t.divider_color, "hairline": True}))

        if policies:
            pol_col_id, pol_comps = _item_rows(policies, g)
            comps.extend(pol_comps)
            col_children.append(pol_col_id)

        if buttons:
            btn_col_id = g("column")
            btn_variant = data.get("button_variant", "primary")
            btn_ids: list[str] = []
            for btn_data in buttons:
                btn_id = g("button")
                btn_ids.append(btn_id)
                comps.append(_comp(btn_id, "Button", {
                    "width": 100,
                    "type": btn_variant,
                    "size": "small",
                    "text": {"literalString": btn_data.get("text", "")},
                    "action": {"name": "query", "args": {"literalString": btn_data.get("action", {})}},
                }))
            comps.append(_comp(btn_col_id, "Column", {
                "gap": t.header_gap,
                "children": {"explicitList": btn_ids},
            }))
            col_children.append(btn_col_id)

        col = _comp(col_id, "Column", {
            "gap": t.section_gap,
            "children": {"explicitList": col_children},
        })
        card = _comp(card_id, "Card", {
            "width": 100,
            "backgroundColor": t.card_bg,
            "borderRadius": t.card_radius,
            "padding": t.card_padding,
            "children": {"explicitList": [col_id]},
        })

        alloc_summary = {
            "title": title,
            "channels": actual_channels,
            "allocations": [
                {"channel": ch, "policy_no": pid, "amount": amt}
                for pid, ch, amt in allocs
            ],
        }
        by_ch: dict[str, float] = {}
        for _, ch, amt in allocs:
            by_ch[ch] = by_ch.get(ch, 0) + amt
        ch_summary = " · ".join(
            f"{_CHANNEL_LABELS.get(ch, ch)} ¥{amt:,.2f}" for ch, amt in by_ch.items()
        )
        channels_str = ",".join(actual_channels)
        digest = (
            f"[卡片:方案 title=\"{title}\" channels=[{channels_str}] total={actual_total:.2f}]"
            f" {ch_summary}"
        )

        return A2UIOutput(
            components=[card, col] + comps,
            llm_digest=digest,
            state_delta={
                "_plan_allocations": [alloc_summary],
                "_submitted_channels": [],
            },
        )

    return {
        "WithdrawSummaryHeader": build_withdraw_summary_header,
        "WithdrawSummarySection": build_withdraw_summary_section,
        "WithdrawPlanCard": build_withdraw_plan_card,
    }


INSURANCE_COMPONENTS: dict[str, Any] = create_insurance_components()

COMPONENT_SCHEMAS: dict[str, str] = {
    "WithdrawSummaryHeader": "总览头：合计所选板块的可领金额",
    "WithdrawSummarySection": "板块卡：列出单板块各保单可领明细",
    "WithdrawPlanCard": "方案卡：按目标金额在候选渠道自动分配",
}

BLOCK_DATA_SCHEMAS: dict[str, dict[str, Any]] = {
    "WithdrawSummaryHeader": {
        "type": "object",
        "properties": {
            "sections": {
                "type": "array",
                "description": "要展示的板块列表；缺省=全部。",
                "items": {"type": "string", "enum": list(SECTION_TYPES)},
            },
            "exclude_policies": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "additionalProperties": True,
    },
    "WithdrawSummarySection": {
        "type": "object",
        "required": ["section_name"],
        "properties": {
            "section_name": {
                "type": "string",
                "description": "要展示的单个板块。",
                "enum": list(SECTION_TYPES),
            },
            "exclude_policies": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "additionalProperties": True,
    },
    "WithdrawPlanCard": {
        "type": "object",
        "required": ["channels"],
        "properties": {
            "channels": {
                "type": "array",
                "description": (
                    "候选渠道，按数组顺序贪心分配 target。"
                    "顺序 = 优先级，把希望先消耗的渠道写在前面。"
                ),
                "items": {"type": "string", "enum": list(CHANNEL_TYPES)},
            },
            "target": {
                "type": "number",
                "description": "目标金额；0 或缺省=channels 累计全额。",
            },
            "is_recommended": {
                "type": "boolean",
                "description": "是否推荐方案（影响标题前缀 \"★ 推荐:\"）。一组方案中至多 1 个为 true。",
            },
            "reason": {"type": "string"},
            "button_variant": {
                "type": "string",
                "enum": ["primary", "secondary"],
            },
            "exclude_policies": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "additionalProperties": True,
    },
}
