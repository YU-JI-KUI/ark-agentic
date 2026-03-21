"""
Composable Block Builders for Dynamic A2UI

Each builder takes (data, id_gen) and returns a list of flat A2UI component dicts
with fixed, hardcoded styling.  The LLM never controls colours / padding / fonts.

Design tokens are extracted from the canonical sample:
  docs/a2ui/a2ui-withdraw-ui-smaple.json
"""

from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Design tokens  (single source of truth for all block styles)
# ---------------------------------------------------------------------------

ACCENT = "#FF6600"
TITLE_COLOR = "#333333"
BODY_COLOR = "#333333"
HINT_COLOR = "#999999"
NOTE_COLOR = "#666666"
CARD_BG = "#FFFFFF"
PAGE_BG = "#F5F5F5"
DIVIDER_COLOR = "#F5F5F5"
CARD_RADIUS = "middle"
CARD_WIDTH = 96
CARD_PADDING = 16
HEADER_PADDING = 20
SECTION_GAP = 12
HEADER_GAP = 8
KV_ROW_WIDTH = 98

# ---------------------------------------------------------------------------
# Binding helpers  (moved from flattener.py – sole owner)
# ---------------------------------------------------------------------------

IdGen = Callable[[str], str]


_TRANSFORM_OPS = frozenset({"get", "sum", "count", "concat", "select", "switch", "literal"})


def resolve_binding(value: Any) -> Any:
    """Expand $field shorthand to standard A2UI binding format."""
    if isinstance(value, str) and value.startswith("$"):
        return {"path": value[1:]}
    if isinstance(value, dict) and ("path" in value or "literalString" in value):
        return value
    if isinstance(value, str):
        return {"literalString": value}
    if isinstance(value, (bool, int, float, list)):
        return {"literalString": value}
    if isinstance(value, dict):
        if _TRANSFORM_OPS & value.keys():
            logger.warning("Unresolved transform spec in resolve_binding: %s", value)
            return {"literalString": "[数据计算失败]"}
        return {"literalString": value}
    return value


def _resolve_action(action: Any) -> Any:
    if not isinstance(action, dict):
        return action
    out = dict(action)
    if "args" in out:
        out["args"] = resolve_binding(out["args"])
    return out


# ---------------------------------------------------------------------------
# Block Registry
# ---------------------------------------------------------------------------

from .guard import BlockDataError

_BLOCK_REGISTRY: dict[str, Callable[[dict[str, Any], IdGen], list[dict[str, Any]]]] = {}
_BLOCK_REQUIRED_KEYS: dict[str, list[str]] = {}


def _register(name: str, required_keys: list[str] | None = None):
    def decorator(fn: Callable[[dict[str, Any], IdGen], list[dict[str, Any]]]):
        if required_keys:
            _BLOCK_REQUIRED_KEYS[name] = required_keys

            def wrapper(data: dict[str, Any], id_gen: IdGen) -> list[dict[str, Any]]:
                missing = [k for k in required_keys if k not in data]
                if missing:
                    raise BlockDataError(name, missing)
                return fn(data, id_gen)

            _BLOCK_REGISTRY[name] = wrapper
        else:
            _BLOCK_REGISTRY[name] = fn
        return fn
    return decorator


def get_block_builder(name: str):
    builder = _BLOCK_REGISTRY.get(name)
    if builder is None:
        raise ValueError(
            f"Unknown block type '{name}'. "
            f"Available: {sorted(_BLOCK_REGISTRY.keys())}"
        )
    return builder


def get_block_types() -> frozenset[str]:
    return frozenset(_BLOCK_REGISTRY.keys())


# ---------------------------------------------------------------------------
# Component helper (reduces boilerplate)
# ---------------------------------------------------------------------------

def _comp(id_: str, comp_type: str, props: dict[str, Any]) -> dict[str, Any]:
    return {"id": id_, "component": {comp_type: props}}


def _text(id_: str, text: Any, **style: Any) -> dict[str, Any]:
    props: dict[str, Any] = {"text": resolve_binding(text)}
    props.update(style)
    return _comp(id_, "Text", props)


# ---------------------------------------------------------------------------
# Block builders
# ---------------------------------------------------------------------------

@_register("SummaryHeader", required_keys=["title", "value"])
def build_summary_header(data: dict[str, Any], g: IdGen) -> list[dict[str, Any]]:
    """Hero header card: title + highlighted value + subtitle + note."""
    card_id, col_id = g("Card"), g("Column")
    title_id, value_id = g("Text"), g("Text")

    children = [title_id, value_id]
    comps: list[dict[str, Any]] = []

    comps.append(_text(title_id, data["title"],
                       color=TITLE_COLOR, fontSize="16px", bold=True))
    comps.append(_text(value_id, data["value"],
                       color=ACCENT, fontSize="24px", bold=True))

    if "subtitle" in data:
        sub_id = g("Text")
        children.append(sub_id)
        comps.append(_text(sub_id, data["subtitle"],
                           color=HINT_COLOR, fontSize="12px"))
    if "note" in data:
        note_id = g("Text")
        children.append(note_id)
        comps.append(_text(note_id, data["note"],
                           color=NOTE_COLOR, fontSize="12px"))

    col = _comp(col_id, "Column", {
        "alignment": "center", "distribution": "center",
        "gap": HEADER_GAP,
        "children": {"explicitList": children},
    })
    card = _comp(card_id, "Card", {
        "width": CARD_WIDTH, "backgroundColor": CARD_BG,
        "borderRadius": CARD_RADIUS, "padding": HEADER_PADDING,
        "children": {"explicitList": [col_id]},
    })
    return [card, col, *comps]


@_register("SectionCard", required_keys=["title", "total", "items"])
def build_section_card(data: dict[str, Any], g: IdGen) -> list[dict[str, Any]]:
    """Titled section: marker + title + tag + total + divider + KV items list."""
    card_id, col_id = g("Card"), g("Column")
    row_id = g("Row")
    marker_id, title_id = g("Text"), g("Text")
    total_id, div_id = g("Text"), g("Divider")

    title_row_children = [marker_id, title_id]
    comps: list[dict[str, Any]] = []

    comps.append(_text(marker_id, "|", color=ACCENT, fontSize="16px", bold=True))
    comps.append(_text(title_id, data["title"],
                       color=TITLE_COLOR, fontSize="16px", bold=True))

    if "tag" in data:
        tag_id = g("Text")
        title_row_children.append(tag_id)
        comps.append(_text(tag_id, data["tag"],
                           color=HINT_COLOR, fontSize="12px"))

    comps.append(_comp(row_id, "Row", {
        "alignment": "middle", "gap": 8,
        "children": {"explicitList": title_row_children},
    }))
    comps.append(_text(total_id, data["total"],
                       color=ACCENT, fontSize="16px", bold=True))
    comps.append(_comp(div_id, "Divider", {
        "borderColor": DIVIDER_COLOR, "hairline": True,
    }))

    col_children: list[str] = [row_id, total_id, div_id]

    # Items rendered via List component
    list_id = g("List")
    child_row_id = g("Row")
    label_id, val_id = g("Text"), g("Text")

    comps.append(_text(label_id, "$item.label", color=BODY_COLOR, fontSize="14px"))
    comps.append(_text(val_id, "$item.value", color=BODY_COLOR, fontSize="14px"))
    comps.append(_comp(child_row_id, "Row", {
        "width": KV_ROW_WIDTH, "distribution": "spaceBetween",
        "children": {"explicitList": [label_id, val_id]},
    }))
    comps.append(_comp(list_id, "List", {
        "direction": "vertical", "gap": 10,
        "dataSource": resolve_binding(data["items"]),
        "child": child_row_id,
    }))
    col_children.append(list_id)

    comps.append(_comp(col_id, "Column", {
        "gap": SECTION_GAP,
        "children": {"explicitList": col_children},
    }))
    comps.append(_comp(card_id, "Card", {
        "width": CARD_WIDTH, "backgroundColor": CARD_BG,
        "borderRadius": CARD_RADIUS, "padding": CARD_PADDING,
        "children": {"explicitList": [col_id]},
    }))
    return [comps[-1]] + comps[:-1]


@_register("InfoCard", required_keys=["title", "body"])
def build_info_card(data: dict[str, Any], g: IdGen) -> list[dict[str, Any]]:
    """Simple card with title + body text."""
    card_id, col_id = g("Card"), g("Column")
    title_id, body_id = g("Text"), g("Text")

    return [
        _comp(card_id, "Card", {
            "width": CARD_WIDTH, "backgroundColor": CARD_BG,
            "borderRadius": CARD_RADIUS, "padding": CARD_PADDING,
            "children": {"explicitList": [col_id]},
        }),
        _comp(col_id, "Column", {
            "gap": HEADER_GAP,
            "children": {"explicitList": [title_id, body_id]},
        }),
        _text(title_id, data["title"],
              color=TITLE_COLOR, fontSize="16px", bold=True),
        _text(body_id, data["body"],
              color=BODY_COLOR, fontSize="14px"),
    ]


@_register("AdviceCard", required_keys=["title"])
def build_advice_card(data: dict[str, Any], g: IdGen) -> list[dict[str, Any]]:
    """Advice block: optional icon + title + list of tip texts."""
    card_id, col_id = g("Card"), g("Column")
    row_id, title_id = g("Row"), g("Text")

    row_children: list[str] = []
    comps: list[dict[str, Any]] = []

    if "icon" in data:
        icon_id = g("Text")
        row_children.append(icon_id)
        comps.append(_text(icon_id, data["icon"], fontSize="16px"))

    row_children.append(title_id)
    comps.append(_text(title_id, data["title"],
                       color=TITLE_COLOR, fontSize="16px", bold=True))
    comps.append(_comp(row_id, "Row", {
        "alignment": "middle", "gap": 8,
        "children": {"explicitList": row_children},
    }))

    col_children: list[str] = [row_id]
    for text_val in data.get("texts", []):
        tid = g("Text")
        col_children.append(tid)
        comps.append(_text(tid, text_val,
                           color=HINT_COLOR, fontSize="14px"))

    col_comp = _comp(col_id, "Column", {
        "gap": 8,
        "children": {"explicitList": col_children},
    })
    card_comp = _comp(card_id, "Card", {
        "width": CARD_WIDTH, "backgroundColor": CARD_BG,
        "borderRadius": CARD_RADIUS, "padding": CARD_PADDING,
        "children": {"explicitList": [col_id]},
    })
    return [card_comp, col_comp, *comps]


@_register("KeyValueList")
def build_key_value_list(data: dict[str, Any], g: IdGen) -> list[dict[str, Any]]:
    """Standalone list of label:value pairs via List component.

    Two modes:
    (1) items: path (e.g. "$items") -> dataSource from payload.data[items].
    (2) row1_label, row1_value, row2_label, ... in payload -> dataSource is
        literal array of {label: {path: "rowN_label"}, value: {path: "rowN_value"}}.
        Block data may specify "rowCount" (default 9) and optionally "rowPrefix" (default "row").
    """
    list_id = g("List")
    row_id = g("Row")
    label_id, val_id = g("Text"), g("Text")

    if "items" in data:
        data_source = resolve_binding(data["items"])
    else:
        row_count = int(data.get("rowCount", 9))
        row_prefix = str(data.get("rowPrefix", "row"))
        data_source = {
            "literalString": [
                {
                    "label": {"path": f"{row_prefix}{i}_label"},
                    "value": {"path": f"{row_prefix}{i}_value"},
                }
                for i in range(1, row_count + 1)
            ]
        }

    return [
        _comp(list_id, "List", {
            "direction": "vertical", "gap": 10,
            "dataSource": data_source,
            "child": row_id,
        }),
        _comp(row_id, "Row", {
            "width": KV_ROW_WIDTH, "distribution": "spaceBetween",
            "children": {"explicitList": [label_id, val_id]},
        }),
        _text(label_id, "$item.label", color=BODY_COLOR, fontSize="14px"),
        _text(val_id, "$item.value", color=BODY_COLOR, fontSize="14px"),
    ]


@_register("DataTable")
def build_data_table(data: dict[str, Any], g: IdGen) -> list[dict[str, Any]]:
    """Table display with column headers and data rows.

    .. deprecated::
        DataTable has structural misalignment (headers use CSS Grid,
        rows use Flexbox). Prefer ``ItemList`` or stacked ``SectionCard``
        blocks for new skills.
    """
    table_id = g("Table")
    columns = data.get("columns", [])
    col_count = len(columns)

    header_ids: list[str] = []
    comps: list[dict[str, Any]] = []
    for col_def in columns:
        hid = g("Text")
        header_ids.append(hid)
        comps.append(_text(hid, col_def.get("header", ""),
                           color=TITLE_COLOR, fontSize="14px", bold=True))

    # Data row template via List
    list_id = g("List")
    row_id = g("Row")
    cell_ids: list[str] = []
    for col_def in columns:
        cid = g("Text")
        cell_ids.append(cid)
        field = col_def.get("field", "")
        comps.append(_text(cid, f"$item.{field}", color=BODY_COLOR, fontSize="14px"))

    comps.append(_comp(row_id, "Row", {
        "distribution": "spaceBetween",
        "children": {"explicitList": cell_ids},
    }))
    comps.append(_comp(list_id, "List", {
        "direction": "vertical", "gap": 8,
        "dataSource": resolve_binding(data.get("data", "")),
        "child": row_id,
    }))

    col_widths = [
        f"{c.get('width', 25)}%" if isinstance(c.get("width"), (int, float))
        else c.get("width", "1fr")
        for c in columns
    ]
    comps.append(_comp(table_id, "Table", {
        "width": 100, "backgroundColor": CARD_BG,
        "borderRadius": CARD_RADIUS,
        "columnCount": col_count,
        "columnWidths": col_widths,
        "children": {"explicitList": header_ids},
    }))

    card_id = g("Card")
    col_id = g("Column")
    comps.append(_comp(col_id, "Column", {
        "gap": 8,
        "children": {"explicitList": [table_id, list_id]},
    }))
    comps.append(_comp(card_id, "Card", {
        "width": CARD_WIDTH, "backgroundColor": CARD_BG,
        "borderRadius": CARD_RADIUS, "padding": CARD_PADDING,
        "children": {"explicitList": [col_id]},
    }))
    return [comps[-1]] + comps[:-1]


@_register("ItemList")
def build_item_list(data: dict[str, Any], g: IdGen) -> list[dict[str, Any]]:
    """List of complex items, each with title + optional tag + value."""
    list_id = g("List")
    item_col_id = g("Column")
    top_row_id = g("Row")
    title_id = g("Text")

    comps: list[dict[str, Any]] = []
    top_row_children: list[str] = [title_id]
    title_field = data.get("titleField", "name")
    comps.append(_text(title_id, f"$item.{title_field}",
                       color=TITLE_COLOR, fontSize="14px", bold=True))

    if "tagField" in data:
        tag_id = g("Tag")
        top_row_children.append(tag_id)
        comps.append(_comp(tag_id, "Tag", {
            "text": resolve_binding(f"$item.{data['tagField']}"),
            "size": "small",
        }))

    comps.append(_comp(top_row_id, "Row", {
        "distribution": "spaceBetween", "alignment": "middle",
        "children": {"explicitList": top_row_children},
    }))

    col_children: list[str] = [top_row_id]
    value_field = data.get("valueField", "value")
    val_id = g("Text")
    col_children.append(val_id)
    comps.append(_text(val_id, f"$item.{value_field}",
                       color=ACCENT, fontSize="16px", bold=True))

    if "subtitleField" in data:
        sub_id = g("Text")
        col_children.append(sub_id)
        comps.append(_text(sub_id, f"$item.{data['subtitleField']}",
                           color=HINT_COLOR, fontSize="12px"))

    comps.append(_comp(item_col_id, "Column", {
        "gap": 6, "padding": 12,
        "backgroundColor": "#FAFAFA", "borderRadius": "small",
        "children": {"explicitList": col_children},
    }))

    card_id = g("Card")
    comps.append(_comp(list_id, "List", {
        "direction": "vertical", "gap": 12,
        "dataSource": resolve_binding(data["items"]),
        "child": item_col_id,
    }))
    comps.append(_comp(card_id, "Card", {
        "width": CARD_WIDTH, "backgroundColor": CARD_BG,
        "borderRadius": CARD_RADIUS, "padding": CARD_PADDING,
        "children": {"explicitList": [list_id]},
    }))
    return [comps[-1]] + comps[:-1]


@_register("ActionButton", required_keys=["text"])
def build_action_button(data: dict[str, Any], g: IdGen) -> list[dict[str, Any]]:
    """Single CTA button."""
    btn_id = g("Button")
    variant = data.get("variant", "primary")
    props: dict[str, Any] = {
        "type": variant,
        "width": CARD_WIDTH,
        "text": resolve_binding(data["text"]),
    }
    if "action" in data:
        props["action"] = _resolve_action(data["action"])
    return [_comp(btn_id, "Button", props)]


@_register("ButtonGroup")
def build_button_group(data: dict[str, Any], g: IdGen) -> list[dict[str, Any]]:
    """Row of multiple buttons."""
    row_id = g("Row")
    btn_ids: list[str] = []
    comps: list[dict[str, Any]] = []

    for btn_data in data.get("buttons", []):
        bid = g("Button")
        btn_ids.append(bid)
        variant = btn_data.get("variant", "primary")
        props: dict[str, Any] = {
            "type": variant,
            "size": "auto",
            "text": resolve_binding(btn_data.get("text", "")),
        }
        if "action" in btn_data:
            props["action"] = _resolve_action(btn_data["action"])
        comps.append(_comp(bid, "Button", props))

    comps.append(_comp(row_id, "Row", {
        "distribution": "spaceAround", "gap": 12,
        "children": {"explicitList": btn_ids},
    }))
    return [comps[-1]] + comps[:-1]


@_register("Divider")
def build_divider(_data: dict[str, Any], g: IdGen) -> list[dict[str, Any]]:
    """Horizontal separator."""
    return [_comp(g("Divider"), "Divider", {
        "borderColor": DIVIDER_COLOR, "hairline": True,
    })]


@_register("TagRow")
def build_tag_row(data: dict[str, Any], g: IdGen) -> list[dict[str, Any]]:
    """Row of tags."""
    row_id = g("Row")
    tag_ids: list[str] = []
    comps: list[dict[str, Any]] = []

    for tag_val in data.get("tags", []):
        tid = g("Tag")
        tag_ids.append(tid)
        if isinstance(tag_val, dict):
            text_binding = resolve_binding(tag_val.get("text", ""))
            props: dict[str, Any] = {"text": text_binding, "size": "small"}
            if "color" in tag_val:
                props["color"] = tag_val["color"]
        else:
            props = {"text": resolve_binding(tag_val), "size": "small"}
        comps.append(_comp(tid, "Tag", props))

    comps.append(_comp(row_id, "Row", {
        "alignment": "middle", "gap": 8,
        "children": {"explicitList": tag_ids},
    }))
    return [comps[-1]] + comps[:-1]


@_register("ImageBanner", required_keys=["url"])
def build_image_banner(data: dict[str, Any], g: IdGen) -> list[dict[str, Any]]:
    """Image display."""
    img_id = g("Image")
    props: dict[str, Any] = {
        "url": resolve_binding(data["url"]),
        "type": "image",
        "size": "auto",
    }
    if "fit" in data:
        props["fit"] = data["fit"]
    return [_comp(img_id, "Image", props)]


@_register("StatusRow", required_keys=["label", "value"])
def build_status_row(data: dict[str, Any], g: IdGen) -> list[dict[str, Any]]:
    """Status indicator: circle + label + value."""
    row_id = g("Row")
    circle_id, label_id, val_id = g("Circle"), g("Text"), g("Text")

    status = data.get("status", "info")
    color_map = {"success": "#33CC66", "warning": ACCENT, "error": "#FF3333", "info": HINT_COLOR}
    dot_color = color_map.get(status, HINT_COLOR)

    return [
        _comp(row_id, "Row", {
            "alignment": "middle", "gap": 8,
            "children": {"explicitList": [circle_id, label_id, val_id]},
        }),
        _comp(circle_id, "Circle", {"backgroundColor": dot_color, "size": "small"}),
        _text(label_id, data["label"], color=BODY_COLOR, fontSize="14px"),
        _text(val_id, data["value"], color=TITLE_COLOR, fontSize="14px", bold=True),
    ]


# ---------------------------------------------------------------------------
# FundsSummary: canonical "how much can withdraw" card (matches sample JSON)
# Data keys: header_title, header_value, header_sub, requested_amount_display,
# section_marker, zero_cost_*, loan_*, advice_*, plan_button_text, plan_action_args
# ---------------------------------------------------------------------------

def _path(path_key: str) -> dict[str, Any]:
    return {"path": path_key}


@_register("FundsSummary")
def build_funds_summary(_data: dict[str, Any], g: IdGen) -> list[dict[str, Any]]:
    """Single block for funds overview card; structure matches a2ui-withdraw-ui-sample.json."""
    wrap_id = g("Column")
    comps: list[dict[str, Any]] = [
        _comp(wrap_id, "Column", {
            "width": 100,
            "backgroundColor": PAGE_BG,
            "padding": 2,
            "gap": 0,
            "children": {"explicitList": [
                "header-card", "card-zero-cost", "card-loan", "card-advice", "btn-get-plan",
            ]},
        }),
        _comp("header-card", "Card", {
            "width": CARD_WIDTH,
            "backgroundColor": CARD_BG,
            "borderRadius": CARD_RADIUS,
            "padding": HEADER_PADDING,
            "children": {"explicitList": ["header-col"]},
        }),
        _comp("header-col", "Column", {
            "alignment": "center",
            "distribution": "center",
            "gap": HEADER_GAP,
            "children": {"explicitList": ["header-title", "header-value", "header-sub", "header-requested"]},
        }),
        _comp("header-requested", "Text", {"text": _path("requested_amount_display"), "color": NOTE_COLOR, "fontSize": "12px"}),
        _comp("header-title", "Text", {"text": _path("header_title"), "color": TITLE_COLOR, "fontSize": "16px", "bold": True}),
        _comp("header-value", "Text", {"text": _path("header_value"), "color": ACCENT, "fontSize": "24px", "bold": True}),
        _comp("header-sub", "Text", {"text": _path("header_sub"), "color": HINT_COLOR, "fontSize": "12px"}),
        _comp("card-zero-cost", "Card", {
            "width": CARD_WIDTH,
            "backgroundColor": CARD_BG,
            "borderRadius": CARD_RADIUS,
            "padding": CARD_PADDING,
            "children": {"explicitList": ["cz-col"]},
        }),
        _comp("cz-col", "Column", {
            "gap": SECTION_GAP,
            "children": {"explicitList": ["cz-title-row", "cz-total", "cz-divider", "cz-item-1", "cz-item-2"]},
        }),
        _comp("cz-title-row", "Row", {
            "alignment": "middle", "gap": 8,
            "children": {"explicitList": ["cz-line", "cz-title", "cz-tag"]},
        }),
        _comp("cz-line", "Text", {"text": _path("section_marker"), "color": ACCENT, "fontSize": "16px", "bold": True}),
        _comp("cz-title", "Text", {"text": _path("zero_cost_title"), "color": TITLE_COLOR, "fontSize": "16px", "bold": True}),
        _comp("cz-tag", "Text", {"text": _path("zero_cost_tag"), "color": HINT_COLOR, "fontSize": "12px"}),
        _comp("cz-total", "Text", {"text": _path("zero_cost_total"), "color": ACCENT, "fontSize": "16px", "bold": True}),
        _comp("cz-divider", "Divider", {"borderColor": DIVIDER_COLOR, "hairline": True}),
        _comp("cz-item-1", "Row", {
            "width": KV_ROW_WIDTH, "distribution": "spaceBetween",
            "children": {"explicitList": ["cz-i1-l", "cz-i1-r"]},
        }),
        _comp("cz-i1-l", "Text", {"text": _path("zero_cost_item_1_label"), "color": BODY_COLOR, "fontSize": "14px"}),
        _comp("cz-i1-r", "Text", {"text": _path("zero_cost_item_1_value"), "color": BODY_COLOR, "fontSize": "14px"}),
        _comp("cz-item-2", "Row", {
            "width": KV_ROW_WIDTH, "distribution": "spaceBetween",
            "children": {"explicitList": ["cz-i2-l", "cz-i2-r"]},
        }),
        _comp("cz-i2-l", "Text", {"text": _path("zero_cost_item_2_label"), "color": BODY_COLOR, "fontSize": "14px"}),
        _comp("cz-i2-r", "Text", {"text": _path("zero_cost_item_2_value"), "color": BODY_COLOR, "fontSize": "14px"}),
        _comp("card-loan", "Card", {
            "width": CARD_WIDTH,
            "backgroundColor": CARD_BG,
            "borderRadius": CARD_RADIUS,
            "padding": CARD_PADDING,
            "children": {"explicitList": ["cl-col"]},
        }),
        _comp("cl-col", "Column", {
            "gap": SECTION_GAP,
            "children": {"explicitList": ["cl-title-row", "cl-total", "cl-divider", "cl-item-1", "cl-item-2"]},
        }),
        _comp("cl-title-row", "Row", {
            "alignment": "middle", "gap": 8,
            "children": {"explicitList": ["cl-line", "cl-title", "cl-tag"]},
        }),
        _comp("cl-line", "Text", {"text": _path("section_marker"), "color": ACCENT, "fontSize": "16px", "bold": True}),
        _comp("cl-title", "Text", {"text": _path("loan_title"), "color": TITLE_COLOR, "fontSize": "16px", "bold": True}),
        _comp("cl-tag", "Text", {"text": _path("loan_tag"), "color": HINT_COLOR, "fontSize": "12px"}),
        _comp("cl-total", "Text", {"text": _path("loan_total"), "color": ACCENT, "fontSize": "16px", "bold": True}),
        _comp("cl-divider", "Divider", {"borderColor": DIVIDER_COLOR, "hairline": True}),
        _comp("cl-item-1", "Row", {
            "width": KV_ROW_WIDTH, "distribution": "spaceBetween",
            "children": {"explicitList": ["cl-i1-l", "cl-i1-r"]},
        }),
        _comp("cl-i1-l", "Text", {"text": _path("loan_item_1_label"), "color": BODY_COLOR, "fontSize": "14px"}),
        _comp("cl-i1-r", "Text", {"text": _path("loan_item_1_value"), "color": BODY_COLOR, "fontSize": "14px"}),
        _comp("cl-item-2", "Row", {
            "width": KV_ROW_WIDTH, "distribution": "spaceBetween",
            "children": {"explicitList": ["cl-i2-l", "cl-i2-r"]},
        }),
        _comp("cl-i2-l", "Text", {"text": _path("loan_item_2_label"), "color": BODY_COLOR, "fontSize": "14px"}),
        _comp("cl-i2-r", "Text", {"text": _path("loan_item_2_value"), "color": BODY_COLOR, "fontSize": "14px"}),
        _comp("card-advice", "Card", {
            "width": CARD_WIDTH,
            "backgroundColor": CARD_BG,
            "borderRadius": CARD_RADIUS,
            "padding": CARD_PADDING,
            "children": {"explicitList": ["ca-col"]},
        }),
        _comp("ca-col", "Column", {
            "gap": 8,
            "children": {"explicitList": ["ca-title-row", "ca-t1", "ca-t2"]},
        }),
        _comp("ca-title-row", "Row", {
            "alignment": "middle", "gap": 8,
            "children": {"explicitList": ["ca-icon", "ca-title"]},
        }),
        _comp("ca-icon", "Text", {"text": _path("advice_icon"), "fontSize": "16px"}),
        _comp("ca-title", "Text", {"text": _path("advice_title"), "color": TITLE_COLOR, "fontSize": "16px", "bold": True}),
        _comp("ca-t1", "Text", {"text": _path("advice_text_1"), "color": HINT_COLOR, "fontSize": "14px"}),
        _comp("ca-t2", "Text", {"text": _path("advice_text_2"), "color": HINT_COLOR, "fontSize": "14px"}),
        _comp("btn-get-plan", "Button", {
            "type": "primary",
            "width": CARD_WIDTH,
            "text": _path("plan_button_text"),
            "action": {"name": "query", "args": _path("plan_action_args")},
        }),
    ]
    return comps
