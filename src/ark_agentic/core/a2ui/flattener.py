"""
Tree Flattener for Dynamic A2UI

DEPRECATED: This module is superseded by the Composable Block System
(blocks.py + composer.py).  _resolve_binding now lives in blocks.py.
Kept for backward compatibility only — do not use in new code.

Flattens a nested A2UI component tree into the standard flat components array
with auto-generated IDs and explicitList references.

Non-standard conveniences (handled by flattener):
  1. Nested children arrays -> flattened to {"explicitList": [...]}
  2. $field shorthand -> expanded to {"path": "field"}

Tolerance layer (deprecated, will be removed):
  - Lowercase type names (column -> Column)
  - Shorthand props (w -> width, bg -> backgroundColor)
  - Old 'field' and 'style' props from deprecated Widget Tree DSL
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any

logger = logging.getLogger(__name__)

ALLOWED_TYPES = frozenset({
    "Row", "Column", "Card", "List", "Table", "Popup",
    "Text", "RichText", "Image", "Icon", "Tag", "Circle",
    "Divider", "Line", "Button",
})

_TYPE_NORMALIZE: dict[str, str] = {
    "column": "Column", "row": "Row", "card": "Card", "popup": "Popup",
    "text": "Text", "richtext": "RichText", "image": "Image", "icon": "Icon",
    "tag": "Tag", "divider": "Divider", "button": "Button", "list": "List",
    "table": "Table", "circle": "Circle", "line": "Line",
    "badge": "Tag", "label": "Tag", "container": "Column", "box": "Column",
    "flex": "Row", "separator": "Divider", "img": "Image", "btn": "Button",
    "txt": "Text", "markdown": "RichText",
}

_PROP_DEPRECATIONS: dict[str, str] = {
    "w": "width", "h": "height", "bg": "backgroundColor",
    "radius": "borderRadius", "align": "alignment", "distribute": "distribution",
    "pos": "position", "z": "zIndex", "minW": "minWidth", "minH": "minHeight",
}

_STYLE_TOKEN_MAP: dict[str, dict[str, Any]] = {
    "title": {"usageHint": "title"},
    "body": {"usageHint": "info", "size": "normal"},
    "hint": {"usageHint": "tips", "size": "small"},
    "secondary": {"usageHint": "tips", "size": "small"},
    "error": {"usageHint": "error"},
    "warning": {"usageHint": "warning"},
    "link": {"usageHint": "link"},
    "value_highlight": {"color": "#FF6600", "bold": True, "size": "xxlarge"},
    "value_accent": {"color": "#FF6600", "bold": True, "size": "large"},
    "section_marker": {"color": "#FF6600", "bold": True, "size": "large"},
    "success": {"color": "#33CC66", "size": "normal"},
}

_BINDING_PROPS = {"text", "url", "name", "dataSource", "hide"}

_CURRENCY_RE = re.compile(r"[¥￥]\s*[\d,]+\.?\d*|[\d,]{4,}\.?\d*\s*[元万亿]")


def _resolve_binding(value: Any) -> Any:
    """Expand $field shorthand to standard binding format."""
    if isinstance(value, str) and value.startswith("$"):
        return {"path": value[1:]}
    if isinstance(value, dict) and ("path" in value or "literalString" in value):
        return value
    if isinstance(value, str):
        return {"literalString": value}
    if isinstance(value, (bool, int, float, list)):
        return {"literalString": value}
    if isinstance(value, dict):
        return {"literalString": value}
    return value


def _normalize_flat_format(node: dict[str, Any]) -> dict[str, Any]:
    """Handle flat-format nodes: {"type": "Column", "props": {...}} -> {"Column": {...}}"""
    if "type" not in node:
        return node
    node_type = str(node["type"]).strip()
    props: dict[str, Any] = {}
    if isinstance(node.get("props"), dict):
        props.update(node["props"])
    for k, v in node.items():
        if k not in ("type", "props"):
            props[k] = v
    if "children" in props and isinstance(props["children"], list):
        props["children"] = [_normalize_flat_format(c) if isinstance(c, dict) else c for c in props["children"]]
    if "child" in props and isinstance(props["child"], dict):
        props["child"] = _normalize_flat_format(props["child"])
    if "emptyChild" in props and isinstance(props["emptyChild"], dict):
        props["emptyChild"] = _normalize_flat_format(props["emptyChild"])
    return {node_type: props}


class TreeFlattener:
    """Flattens a nested A2UI component tree into standard flat format."""

    def __init__(self) -> None:
        self._components: list[dict[str, Any]] = []
        self._counter: int = 0
        self._warnings: list[str] = []

    def flatten(
        self,
        tree: dict[str, Any],
        data: dict[str, Any],
        event: str = "beginRendering",
        surface_id: str = "",
        session_id: str = "",
    ) -> dict[str, Any]:
        self._components = []
        self._counter = 0
        self._warnings = []

        tree = _normalize_flat_format(tree)
        root_id = self._walk(tree, depth=0)

        if not surface_id:
            prefix = (session_id or "")[:8]
            surface_id = f"dyn-{prefix}-{uuid.uuid4().hex[:6]}"

        return {
            "event": event,
            "version": "1.0.0",
            "surfaceId": surface_id,
            "rootComponentId": root_id,
            "components": self._components,
            "style": "default",
            "data": data,
            "hideVoteRecorder": False,
        }

    @property
    def warnings(self) -> list[str]:
        return list(self._warnings)

    def _gen_id(self, comp_type: str) -> str:
        self._counter += 1
        return f"{comp_type}-{self._counter:03d}"

    def _walk(self, node: dict[str, Any], depth: int) -> str:
        if depth > 50:
            raise ValueError("Component tree exceeds 50 levels")
        if not isinstance(node, dict) or not node:
            raise ValueError(f"Invalid node: {node}")

        raw_type = next(iter(node))
        raw_props = node[raw_type]
        props = dict(raw_props) if isinstance(raw_props, dict) else {}

        comp_type = _TYPE_NORMALIZE.get(raw_type, raw_type)
        if raw_type != comp_type:
            self._warnings.append(f"[DEPRECATED] type '{raw_type}' -> use '{comp_type}'")

        if comp_type not in ALLOWED_TYPES:
            raise ValueError(
                f"Unknown component type '{raw_type}'. "
                f"Allowed: {sorted(ALLOWED_TYPES)}"
            )

        comp_id = props.pop("id", None) or self._gen_id(comp_type)
        result_props = self._normalize_props(props, comp_type, depth)

        if comp_type == "Popup":
            result_props.setdefault("modelValue", False)
            result_props.setdefault("overlay", True)

        self._components.append({
            "id": comp_id,
            "component": {comp_type: result_props},
        })
        return comp_id

    def _normalize_props(
        self, props: dict[str, Any], comp_type: str, depth: int,
    ) -> dict[str, Any]:
        out: dict[str, Any] = {}

        for key, value in props.items():
            if key in _PROP_DEPRECATIONS:
                new_key = _PROP_DEPRECATIONS[key]
                self._warnings.append(f"[DEPRECATED] prop '{key}' -> use '{new_key}'")
                out[new_key] = value
            elif key == "field":
                self._warnings.append("[DEPRECATED] 'field' -> use 'text' with binding")
                out["text"] = _resolve_binding(value)
            elif key == "style":
                token = _STYLE_TOKEN_MAP.get(str(value), {})
                if token:
                    self._warnings.append(
                        f"[DEPRECATED] 'style: {value}' -> use usageHint/size/bold/color"
                    )
                    for tk, tv in token.items():
                        out.setdefault(tk, tv)
            elif key == "children":
                if isinstance(value, list):
                    child_ids = [self._walk(c, depth + 1) for c in value]
                    out["children"] = {"explicitList": child_ids}
                else:
                    out["children"] = value
            elif key == "child":
                out["child"] = self._walk_child_ref(value, depth)
            elif key == "emptyChild":
                out["emptyChild"] = self._walk_child_ref(value, depth)
            elif key == "action":
                out["action"] = self._normalize_action(value)
            elif key in _BINDING_PROPS:
                out[key] = _resolve_binding(value)
            else:
                out[key] = value

        return out

    def _walk_child_ref(self, value: Any, depth: int) -> Any:
        """Process child/emptyChild: inline dict -> walk and return ID, string -> pass through."""
        if isinstance(value, dict) and len(value) == 1:
            key = next(iter(value))
            if key in ALLOWED_TYPES or key in _TYPE_NORMALIZE:
                return self._walk(value, depth + 1)
        if isinstance(value, str):
            return value
        return value

    @staticmethod
    def _normalize_action(action: Any) -> Any:
        if not isinstance(action, dict):
            return action
        result = dict(action)
        if "args" in result:
            result["args"] = _resolve_binding(result["args"])
        return result

    @staticmethod
    def soft_validate(
        payload: dict[str, Any], transform_keys: set[str] | None = None,
    ) -> list[str]:
        """Scan for hardcoded numeric values in text fields."""
        warnings: list[str] = []
        computed = transform_keys or set()

        for entry in payload.get("components", []):
            comp_id = entry.get("id", "?")
            for comp_type, comp_props in entry.get("component", {}).items():
                if comp_type not in ("Text", "RichText", "Tag"):
                    continue
                text_spec = comp_props.get("text", {})
                if isinstance(text_spec, dict):
                    literal = text_spec.get("literalString")
                    if isinstance(literal, str) and _CURRENCY_RE.search(literal):
                        warnings.append(
                            f"[SOFT_WARN] component '{comp_id}' ({comp_type}) "
                            f"包含疑似硬编码金额: {literal}"
                        )

        for key, value in payload.get("data", {}).items():
            if key in computed:
                continue
            if isinstance(value, str) and _CURRENCY_RE.search(value):
                warnings.append(f"[SOFT_WARN] data['{key}'] 包含疑似硬编码金额: {value}")

        return warnings
