"""
LeanTemplateRegistry — preset mode card registry.

In preset mode the backend sends `{ template_type, data }` and the frontend
renders a prebuilt component.  Each `template_type` is registered with a
builder that returns A2UIOutput: template_data for UI, plus optional
llm_digest / state_delta for LLM context and session state.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from .blocks import A2UIOutput

logger = logging.getLogger(__name__)

LeanCardBuilder = Callable[[dict[str, Any]], A2UIOutput]

_LEAN_REGISTRY: dict[str, LeanCardBuilder] = {}


def register_lean_card(template_type: str, builder: LeanCardBuilder) -> None:
    """Register a preset card builder for a given template_type."""
    _LEAN_REGISTRY[template_type] = builder


def get_lean_builder(template_type: str) -> LeanCardBuilder | None:
    return _LEAN_REGISTRY.get(template_type)


def build_lean_payload(
    template_type: str, data: dict[str, Any]
) -> tuple[dict[str, Any], A2UIOutput]:
    """Build a preset-mode payload and return enrichment metadata.

    Returns (payload_dict, A2UIOutput). Callers use the payload for the
    frontend event and A2UIOutput.llm_digest / .state_delta for metadata routing.
    """
    builder = _LEAN_REGISTRY.get(template_type)
    output = builder(data) if builder else A2UIOutput(template_data=data)
    payload = {
        "template_type": template_type,
        "data": output.template_data,
    }
    return payload, output


def list_lean_types() -> list[str]:
    return sorted(_LEAN_REGISTRY.keys())
