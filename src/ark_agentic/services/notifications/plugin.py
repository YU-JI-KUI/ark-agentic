"""NotificationsPlugin — built-in notifications feature.

Implements the ``Plugin`` Protocol: schema init in sqlite mode, route
mount on app load, NotificationsContext built in lifespan and attached to
``app_ctx.notifications``.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from ...core.plugin import BasePlugin


def _env_flag(name: str) -> bool:
    return os.getenv(name, "").lower() in ("true", "1")


def _db_is_sqlite() -> bool:
    return os.getenv("DB_TYPE", "file").strip().lower() == "sqlite"


class NotificationsPlugin(BasePlugin):
    """Notifications feature plugin (REST + SSE + repo cache)."""

    name = "notifications"

    def is_enabled(self) -> bool:
        # Backward compat: notifications today come on alongside the
        # job manager. ``ENABLE_NOTIFICATIONS`` lets future setups opt
        # in without enabling jobs.
        return _env_flag("ENABLE_NOTIFICATIONS") or _env_flag("ENABLE_JOB_MANAGER")

    async def init_schema(self) -> None:
        if not _db_is_sqlite():
            return
        from .engine import init_schema
        await init_schema()

    def install_routes(self, app: Any) -> None:
        from .setup import setup_notifications
        setup_notifications(app)

    @asynccontextmanager
    async def lifespan(self, app_ctx: Any) -> AsyncIterator[Any]:
        from .setup import build_notifications_context
        ctx = build_notifications_context()
        try:
            yield ctx
        finally:
            pass  # SSE delivery has no shutdown hooks today
