"""Typed application context — replaces ad-hoc ``app.state`` lookups.

Each independent feature contributes its own ``*Context`` (defined in
that feature's package); the aggregate ``AppContext`` is exposed via
the ``get_ctx`` FastAPI dependency.

This keeps core unaware of feature shapes (forward refs only) while
giving handlers a single typed entry point instead of ``getattr``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from fastapi import Request

if TYPE_CHECKING:
    from ..services.notifications.setup import NotificationsContext


@dataclass
class AppContext:
    notifications: "NotificationsContext | None" = None


def get_ctx(request: Request) -> AppContext:
    """FastAPI dependency: returns the application context populated by
    ``app.py`` lifespan. Raises ``AttributeError`` if accessed before
    lifespan ran (programmer error)."""
    ctx = getattr(request.app.state, "ctx", None)
    if ctx is None:
        raise RuntimeError(
            "AppContext is not initialised — did lifespan run?",
        )
    return ctx
