"""Typed application context — single source of truth for the request scope.

Each plugin's ``lifespan`` may yield a context value that the host
attaches to a typed field on ``AppContext``. Handlers access them via
``Depends(get_ctx)`` instead of ``getattr(app.state, ...)``.

Plugins remain forward-referenced so ``api/`` does not pull each
plugin's package at import time.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from fastapi import Request

if TYPE_CHECKING:
    from ...core.registry import AgentRegistry
    from ..jobs.plugin import JobsContext
    from ..notifications.setup import NotificationsContext


@dataclass
class AppContext:
    """Aggregate runtime state populated by plugins' lifespans + the host.

    Each field is ``None`` when its owning plugin is disabled, so handlers
    can render a 503 instead of crashing.
    """

    registry: "AgentRegistry | None" = None
    notifications: "NotificationsContext | None" = None
    jobs: "JobsContext | None" = None


def get_ctx(request: Request) -> AppContext:
    """FastAPI dependency: returns the application context populated by
    ``app.py`` lifespan. Raises ``RuntimeError`` if accessed before
    lifespan ran (programmer error)."""
    ctx = getattr(request.app.state, "ctx", None)
    if ctx is None:
        raise RuntimeError(
            "AppContext is not initialised — did lifespan run?",
        )
    return ctx
