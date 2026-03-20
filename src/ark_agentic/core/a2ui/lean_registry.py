"""
LeanTemplateRegistry — preset mode card registry.

In preset mode the backend sends `{ template_type, data }` and the frontend
renders a prebuilt component.  Each `template_type` is registered with a
builder that validates/enriches the raw data dict.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)

LeanCardBuilder = Callable[[dict[str, Any]], dict[str, Any]]

_LEAN_REGISTRY: dict[str, LeanCardBuilder] = {}


def register_lean_card(template_type: str, builder: LeanCardBuilder) -> None:
    """Register a preset card builder for a given template_type."""
    _LEAN_REGISTRY[template_type] = builder


def get_lean_builder(template_type: str) -> LeanCardBuilder | None:
    return _LEAN_REGISTRY.get(template_type)


def build_lean_payload(template_type: str, data: dict[str, Any]) -> dict[str, Any]:
    """Build a preset-mode payload: { template_type, data }.

    If a builder is registered it is called to validate/enrich;
    otherwise the data dict is passed through as-is.
    """
    builder = _LEAN_REGISTRY.get(template_type)
    enriched = builder(data) if builder else data
    return {
        "template_type": template_type,
        "data": enriched,
    }


def list_lean_types() -> list[str]:
    return sorted(_LEAN_REGISTRY.keys())
