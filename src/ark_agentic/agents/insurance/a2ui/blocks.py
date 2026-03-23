"""
Insurance agent leaf block builders.

Each builder: (data: dict, id_gen: IdGen) -> list[A2UIComponent].
Styles strictly match the 3 template.json files in templates/.
"""

from __future__ import annotations

from typing import Any

from ark_agentic.core.a2ui.blocks import (
    _comp,
    _text,
    _resolve_action,
    IdGen,
    ACCENT,
    TITLE_COLOR,
    BODY_COLOR,
    HINT_COLOR,
    NOTE_COLOR,
    DIVIDER_COLOR,
)


def build_section_header(data: dict[str, Any], g: IdGen) -> list[dict[str, Any]]:
    """Row(alignment:middle, gap:8) > [Line(#FF6600), Text(title), optional Tag]"""
    row_id = g("row")
    line_id, title_id = g("line"), g("text")

    row_children = [line_id, title_id]
    comps: list[dict[str, Any]] = []

    comps.append(_comp(line_id, "Line", {
        "backgroundColor": ACCENT,
        "minWidth": "3px",
        "minHeight": "16px",
        "borderRadius": "small",
    }))
    comps.append(_text(title_id, data.get("title", ""),
                       color=TITLE_COLOR, fontSize="16px", bold=True))

    if "tag" in data:
        tag_id = g("tag")
        row_children.append(tag_id)
        comps.append(_comp(tag_id, "Tag", {
            "text": {"literalString": data["tag"]},
            "color": data.get("tag_color", HINT_COLOR),
            "size": "small",
        }))

    comps.append(_comp(row_id, "Row", {
        "alignment": "middle",
        "gap": 8,
        "children": {"explicitList": row_children},
    }))
    return [comps[-1]] + comps[:-1]


def build_kv_row(data: dict[str, Any], g: IdGen) -> list[dict[str, Any]]:
    """Row(width:100, spaceBetween) > [Text(label, #666), Text(value, #333)]"""
    row_id = g("row")
    label_id, val_id = g("text"), g("text")

    label_color = data.get("label_color", NOTE_COLOR)
    value_color = data.get("value_color", BODY_COLOR)
    bold = data.get("bold", False)

    return [
        _comp(row_id, "Row", {
            "width": 100,
            "distribution": "spaceBetween",
            "children": {"explicitList": [label_id, val_id]},
        }),
        _text(label_id, data.get("label", ""),
              color=label_color, fontSize="14px", **( {"bold": True} if bold else {})),
        _text(val_id, data.get("value", ""),
              color=value_color, fontSize="14px", **( {"bold": True} if bold else {})),
    ]


def build_accent_total(data: dict[str, Any], g: IdGen) -> list[dict[str, Any]]:
    """With label: Row(spaceBetween) > [Text(label, bold), Text(value, #FF6600, bold)].
    Without label: Text(value, #FF6600, 16px, bold)."""
    value = data.get("value", "")
    label = data.get("label")

    if label:
        row_id = g("row")
        label_id, val_id = g("text"), g("text")
        return [
            _comp(row_id, "Row", {
                "width": 100,
                "distribution": "spaceBetween",
                "children": {"explicitList": [label_id, val_id]},
            }),
            _text(label_id, label, color=TITLE_COLOR, fontSize="14px", bold=True),
            _text(val_id, value, color=ACCENT, fontSize="14px", bold=True),
        ]

    val_id = g("text")
    return [_text(val_id, value, color=ACCENT, fontSize="16px", bold=True)]


def build_hint_text(data: dict[str, Any], g: IdGen) -> list[dict[str, Any]]:
    """Text(text, color, fontSize)"""
    color = data.get("color", HINT_COLOR)
    size = data.get("size", "small")
    font_size = "13px" if size == "medium" else "12px"
    tid = g("text")
    return [_text(tid, data.get("text", ""), color=color, fontSize=font_size)]


def build_action_button(data: dict[str, Any], g: IdGen) -> list[dict[str, Any]]:
    """Button(type, width:100, size:small, text, action)"""
    btn_id = g("button")
    variant = data.get("variant", "primary")
    props: dict[str, Any] = {
        "type": variant,
        "width": 100,
        "size": "small",
        "text": {"literalString": data.get("text", "")},
    }
    if "action" in data:
        props["action"] = _resolve_action(data["action"])
    return [_comp(btn_id, "Button", props)]


def build_divider(data: dict[str, Any], g: IdGen) -> list[dict[str, Any]]:
    """Divider(borderColor:#F5F5F5, hairline:true)"""
    return [_comp(g("divider"), "Divider", {
        "borderColor": DIVIDER_COLOR,
        "hairline": True,
    })]


INSURANCE_BLOCKS: dict[str, Any] = {
    "SectionHeader": build_section_header,
    "KVRow": build_kv_row,
    "AccentTotal": build_accent_total,
    "HintText": build_hint_text,
    "ActionButton": build_action_button,
    "Divider": build_divider,
}
