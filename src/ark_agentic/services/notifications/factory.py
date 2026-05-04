"""Notifications repository factory — env-driven backend dispatch.

Self-contained: the notifications feature owns its own backend selection so
core no longer knows the storage layout. The phase-4 cleanup will hide
``engine`` behind a per-domain ``engine.py`` module; for now the signature
matches the prior ``core.storage.factory.build_notification_repository``.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncEngine

# Importing the storage package as a side-effect registers ``NotificationRow``
# on ``core.db.base.Base.metadata`` so ``init_schema()`` can create the table.
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


def _require_engine(engine: AsyncEngine | None) -> AsyncEngine:
    if engine is not None:
        return engine
    from ...core.db.engine import get_async_engine
    return get_async_engine()


def build_notification_repository(
    base_dir: str | Path | None = None,
    engine: AsyncEngine | None = None,
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
        return SqliteNotificationRepository(
            _require_engine(engine), agent_id=agent_id,
        )
    raise ValueError(
        f"Unsupported DB_TYPE for notification repository: {db_type!r}"
    )
