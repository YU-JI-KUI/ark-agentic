"""ark-agentic Agents — bundled agent implementations.

Agents are *products*, not infrastructure. They live alongside ``core/``
and ``plugins/`` (built-in features) but are registered through their own
auto-discovery mechanism so the host app does not need to know which
agents exist at composition time.

Each agent package may expose a top-level ``register(registry, **opts)``
function. ``register_all`` walks every direct sub-package and calls it.
Failures are logged and skipped so one broken agent never blocks the
others.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..core.registry import AgentRegistry

logger = logging.getLogger(__name__)


def register_all(registry: "AgentRegistry", **opts: Any) -> None:
    """Auto-discover and register every bundled agent.

    Each direct sub-package may define ``register(registry, **opts)``.
    Common ``opts`` include ``enable_memory`` and ``enable_dream``;
    individual agents pick what they need and ignore the rest via ``**_``.
    """
    for _finder, name, ispkg in pkgutil.iter_modules(__path__):
        if not ispkg:
            continue
        try:
            mod = importlib.import_module(f".{name}", __name__)
        except Exception:
            logger.warning(
                "Agent package %r failed to import; skipped", name,
                exc_info=True,
            )
            continue

        register = getattr(mod, "register", None)
        if register is None:
            continue
        try:
            register(registry, **opts)
            logger.info("Registered agent: %s", name)
        except Exception:
            logger.warning(
                "Failed to register agent %r; skipped", name, exc_info=True,
            )
