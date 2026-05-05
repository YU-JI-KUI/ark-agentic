"""Notifications repository factory — mode-driven backend dispatch.

Self-contained: the notifications feature owns its backend selection so
core does not know the storage layout. ``AsyncEngine`` lives in
``services/notifications/engine.py``; this factory never sees it.
"""

from __future__ import annotations

from pathlib import Path

from ...core.storage import mode
from .protocol import NotificationRepository
from .storage.file import FileNotificationRepository
from .storage.sqlite import SqliteNotificationRepository


def build_notification_repository(
    base_dir: str | Path | None = None,
    *,
    agent_id: str = "",
) -> NotificationRepository:
    """Build a notification repository scoped to one ``agent_id``.

    File backend isolates by directory (``base_dir`` already includes the
    agent path); SQLite backend isolates by ``agent_id`` column filtering.
    """
    active = mode.current()
    if active == "file":
        if base_dir is None:
            raise ValueError(
                "NotificationRepository requires 'base_dir' when DB_TYPE=file."
            )
        return FileNotificationRepository(Path(base_dir))
    if active == "sqlite":
        from .engine import get_engine
        return SqliteNotificationRepository(get_engine(), agent_id=agent_id)
    raise ValueError(
        f"Unsupported storage mode for notification repository: {active!r}"
    )
