"""Notifications repository factory — env-driven backend dispatch.

Self-contained: the notifications feature owns its backend selection so
core does not know the storage layout. ``AsyncEngine`` lives in
``services/notifications/engine.py``; this factory never sees it.
"""

from __future__ import annotations

import os
from pathlib import Path

from .protocol import NotificationRepository
from .storage.file import FileNotificationRepository
from .storage.sqlite import SqliteNotificationRepository


def _resolve_db_type() -> str:
    raw = os.environ.get("DB_TYPE", "file").strip().lower()
    if raw not in ("file", "sqlite"):
        raise ValueError(
            f"Unsupported DB_TYPE={raw!r}; expected 'file' or 'sqlite'"
        )
    return raw


def build_notification_repository(
    base_dir: str | Path | None = None,
    *,
    agent_id: str = "",
) -> NotificationRepository:
    """Build a notification repository scoped to one ``agent_id``.

    File backend isolates by directory (``base_dir`` already includes the
    agent path); SQLite backend isolates by ``agent_id`` column filtering.
    """
    db_type = _resolve_db_type()
    if db_type == "file":
        if base_dir is None:
            raise ValueError(
                "NotificationRepository requires 'base_dir' when DB_TYPE=file."
            )
        return FileNotificationRepository(Path(base_dir))
    if db_type == "sqlite":
        from .engine import get_engine
        return SqliteNotificationRepository(get_engine(), agent_id=agent_id)
    raise ValueError(
        f"Unsupported DB_TYPE for notification repository: {db_type!r}"
    )
