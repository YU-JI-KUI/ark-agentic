"""
BlockComposer: assembles block descriptors into a standard A2UI payload.

Each block descriptor is a dict with "type" and "data" keys.
The composer looks up the builder in the block registry, calls it,
and wraps all emitted components in a root Column with PAGE_BG styling.
"""

from __future__ import annotations

import itertools
import uuid
from typing import Any

from .blocks import PAGE_BG, get_block_builder


class BlockComposer:
    """Expand block descriptors into a complete A2UI event payload."""

    def compose(
        self,
        block_descriptors: list[dict[str, Any]],
        data: dict[str, Any],
        event: str = "beginRendering",
        surface_id: str = "",
        session_id: str = "",
    ) -> dict[str, Any]:
        counter = itertools.count(1)

        def id_gen(prefix: str) -> str:
            return f"{prefix.lower()}-{next(counter):03d}"

        root_children: list[str] = []
        all_components: list[dict[str, Any]] = []

        for descriptor in block_descriptors:
            block_type = descriptor.get("type", "")
            block_data = descriptor.get("data", {})

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
                    "padding": 2,
                    "gap": 0,
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
