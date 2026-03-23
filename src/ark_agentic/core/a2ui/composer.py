"""
BlockComposer: assembles block descriptors into a standard A2UI payload.

Each block descriptor is a dict with "type" and "data" keys.
The composer looks up the builder in the block registry, calls it,
and wraps all emitted components in a root Column with PAGE_BG styling.

Supports inline transform specs in block data values: when a value is a dict
containing a transform operator key (get/sum/count/concat/select/switch/literal),
it is resolved at compose-time against raw_data.
"""

from __future__ import annotations

import itertools
import logging
import uuid
from typing import Any

from .blocks import PAGE_BG, get_block_builder
from .transforms import _exec_one

logger = logging.getLogger(__name__)

_TRANSFORM_KEYS = frozenset({"get", "sum", "count", "concat", "select", "switch", "literal"})


def _is_transform_spec(v: Any) -> bool:
    """Check if a value is an inline transform spec (dict with an operator key)."""
    return isinstance(v, dict) and bool(_TRANSFORM_KEYS & v.keys())


def _resolve_value(v: Any, raw_data: dict[str, Any]) -> Any:
    """Resolve a single value: transform spec → computed, otherwise passthrough."""
    if _is_transform_spec(v):
        return _exec_one(v, raw_data)
    if isinstance(v, dict):
        return resolve_block_data(v, raw_data)
    if isinstance(v, list):
        return [_resolve_value(item, raw_data) for item in v]
    return v


def resolve_block_data(data: dict[str, Any], raw_data: dict[str, Any]) -> dict[str, Any]:
    """Resolve inline transform specs in block data before passing to builders."""
    resolved: dict[str, Any] = {}
    for k, v in data.items():
        try:
            resolved[k] = _resolve_value(v, raw_data)
        except Exception as e:
            logger.warning("Inline transform failed for key '%s': %s", k, e)
            resolved[k] = v
    return resolved


class BlockComposer:
    """Expand block descriptors into a complete A2UI event payload."""

    def compose(
        self,
        block_descriptors: list[dict[str, Any]],
        data: dict[str, Any],
        event: str = "beginRendering",
        surface_id: str = "",
        session_id: str = "",
        raw_data: dict[str, Any] | None = None,
        block_registry: dict[str, Any] | None = None,
        root_gap: int = 0,
        root_padding: int | list[int] = 2,
    ) -> dict[str, Any]:
        counter = itertools.count(1)

        def id_gen(prefix: str) -> str:
            return f"{prefix.lower()}-{next(counter):03d}"

        root_children: list[str] = []
        all_components: list[dict[str, Any]] = []

        for descriptor in block_descriptors:
            block_type = descriptor.get("type", "")
            block_data = descriptor.get("data", {})

            if raw_data:
                block_data = resolve_block_data(block_data, raw_data)

            builder = (block_registry or {}).get(block_type)
            if not builder:
                builder = get_block_builder(block_type)
            components = builder(block_data, id_gen)

            if components:
                root_children.append(components[0]["id"])
                all_components.extend(components)

        root_id = id_gen("root")
        root_component: dict[str, Any] = {
            "id": root_id,
            "component": {
                "Column": {
                    "width": 100,
                    "backgroundColor": PAGE_BG,
                    "padding": root_padding,
                    "gap": root_gap,
                    "children": {"explicitList": root_children},
                }
            },
        }

        prefix = (session_id or "").strip()[:8] if (session_id or "").strip() else "default"
        sid = surface_id or f"dyn-{prefix}-{uuid.uuid4().hex[:8]}"

        payload: dict[str, Any] = {
            "event": event,
            "version": "1.0.0",
            "surfaceId": sid,
            "rootComponentId": root_id,
            "style": "default",
            "data": data,
            "components": [root_component] + all_components,
        }
        return payload
