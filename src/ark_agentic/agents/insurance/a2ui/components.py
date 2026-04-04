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
    _CHANNEL_LABELS,
    _allocate_to_target,
    _allocs_to_plan_parts,
    _channel_available,
    _fmt,
    _resolve_channel_filters,
)

logger = logging.getLogger(__name__)


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
        "loan": {
            "channels": ("policy_loan",),
            "title": "保单贷款",
            "tag": "需支付利息",
            "tag_color": "#FF8800",
            "line_color": t.accent,
            "total_color": t.accent,
        },
        "partial_surrender": {
            "channels": ("partial_withdrawal", "surrender"),
            "title": "部分领取/退保",
            "tag": "保障有损失，不建议",
            "tag_color": "#CC6600",
            "line_color": "#CC6600",
            "total_color": t.hint_color,
        },
    }

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
        sections = data.get("sections", ["zero_cost", "loan", "partial_surrender"])
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

        digest = f"汇总: 总可领{'(含贷款)' if has_loan_section else ''} ¥{total:,.2f}"
        if has_loan_section:
            digest += f" | 不含贷款 ¥{total_excl_loan:,.2f}"

        return A2UIOutput(components=[card, col] + comps, llm_digest=digest)

    def build_withdraw_summary_section(
        data: dict[str, Any],
        g: IdGen,
        raw_data: dict[str, Any],
    ) -> A2UIOutput:
        """Section card for withdraw summary."""
        section_name = data.get("section")
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

        detail = "; ".join(f"{item['label']} {item['value']}" for item in items)
        digest = f"渠道: {title} | 合计: ¥{total_sum:,.2f} | {detail}"

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

        channels = data.get("channels", [])
        target = float(data.get("target") or 0)
        title = data.get("title", "")
        tag_text = data.get("tag", "")
        reason = data.get("reason", "")

        if target <= 0:
            target = sum(_channel_available(o, ch) for o in options for ch in channels)

        allocs = _allocate_to_target(options, target, channels)
        actual_total = sum(a for _, _, a in allocs)
        policies, buttons = _allocs_to_plan_parts(allocs)

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
            tag_color = data.get("tag_color", "#52C41A")
            comps.append(_text(tag_tid, tag_text, color=tag_color, fontSize="12px"))

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
            "channels": channels,
            "allocations": [
                {"channel": ch, "policy_no": pid, "amount": amt}
                for pid, ch, amt in allocs
            ],
        }
        detail = "; ".join(f"{pid}({ch}) ¥{amt:,.2f}" for pid, ch, amt in allocs)
        digest = f"方案: {title} | channels: {channels} | 总额: ¥{actual_total:,.2f}"
        if detail:
            digest += f" | 明细: {detail}"

        return A2UIOutput(
            components=[card, col] + comps,
            llm_digest=digest,
            state_delta={"_plan_allocations": [alloc_summary]},
        )

    return {
        "WithdrawSummaryHeader": build_withdraw_summary_header,
        "WithdrawSummarySection": build_withdraw_summary_section,
        "WithdrawPlanCard": build_withdraw_plan_card,
    }


INSURANCE_COMPONENTS: dict[str, Any] = create_insurance_components()
