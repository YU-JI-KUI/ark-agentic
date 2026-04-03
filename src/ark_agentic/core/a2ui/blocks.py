"""
A2UI Block Infrastructure: helpers, registry, and backward-compat token aliases.

Visual design tokens are defined in ``theme.py`` (``A2UITheme``).
The module-level constants below (ACCENT, PAGE_BG, …) are aliases derived from
the default theme instance — kept for backward compatibility with existing agent
imports.  New code should prefer ``A2UITheme`` directly.

Concrete block builders are registered by each agent (e.g. insurance/a2ui/blocks.py).
Core keeps only the shared toolkit; the registry starts empty.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from .theme import A2UITheme

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Design token aliases (backward-compat — canonical values live in A2UITheme)
# ---------------------------------------------------------------------------

_DEFAULT_THEME = A2UITheme()

ACCENT = _DEFAULT_THEME.accent
TITLE_COLOR = _DEFAULT_THEME.title_color
BODY_COLOR = _DEFAULT_THEME.body_color
HINT_COLOR = _DEFAULT_THEME.hint_color
NOTE_COLOR = _DEFAULT_THEME.note_color
CARD_BG = _DEFAULT_THEME.card_bg
PAGE_BG = _DEFAULT_THEME.page_bg
DIVIDER_COLOR = _DEFAULT_THEME.divider_color
CARD_RADIUS = _DEFAULT_THEME.card_radius

# ---------------------------------------------------------------------------
# Binding helpers  (moved from flattener.py – sole owner)
# ---------------------------------------------------------------------------

IdGen = Callable[[str], str]


@dataclass
class A2UIOutput:
    """One data computation, multiple consumers.

    components    -> blocks path: UI component list for frontend
    template_data -> template/preset path: flat dict for template rendering
    llm_digest    -> LLM conversation context (replaces masked stub)
    state_delta   -> session state for downstream tool auto-fill
    """

    components: list[dict[str, Any]] = field(default_factory=list)
    template_data: dict[str, Any] = field(default_factory=dict)
    llm_digest: str = ""
    state_delta: dict[str, Any] | None = None


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


# (Registry is empty — concrete builders are registered by each agent.)
