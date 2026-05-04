"""Notifications feature wiring — owns its own FastAPI router mount.

Phase 1 keeps this minimal: it mounts the notifications router on the app.
Phase 4 will introduce ``NotificationsContext`` here and switch the API
to FastAPI ``Depends`` instead of ``app.state`` lookup.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI


def setup_notifications(app: "FastAPI") -> None:
    """Mount notification + jobs REST/SSE routes on ``app``.

    Called by ``app.py`` lifespan when ``ENABLE_JOB_MANAGER=1``.
    """
    from ...api import notifications as notifications_api

    app.include_router(notifications_api.router)
