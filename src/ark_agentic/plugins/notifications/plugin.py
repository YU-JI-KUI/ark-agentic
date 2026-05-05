"""NotificationsPlugin — built-in notifications feature."""

from __future__ import annotations

import os
from typing import Any

from ...core.protocol.plugin import BasePlugin
from ...core.storage import mode


def _env_flag(name: str) -> bool:
    return os.getenv(name, "").lower() in ("true", "1")


class NotificationsPlugin(BasePlugin):
    """Notifications feature plugin (REST + SSE + repo cache)."""

    name = "notifications"

    def is_enabled(self) -> bool:
        # Backward compat: notifications today come on alongside the
        # job manager. ``ENABLE_NOTIFICATIONS`` lets future setups opt
        # in without enabling jobs.
        return _env_flag("ENABLE_NOTIFICATIONS") or _env_flag("ENABLE_JOB_MANAGER")

    async def init(self) -> None:
        if not mode.is_database():
            return
        from .engine import init_schema
        await init_schema()

    def install_routes(self, app: Any) -> None:
        from .setup import setup_notifications
        setup_notifications(app)

    async def start(self, ctx: Any) -> Any:
        from .setup import build_notifications_context
        return build_notifications_context()

    # stop() inherits BaseLifecycle no-op; SSE delivery has no shutdown hooks.
