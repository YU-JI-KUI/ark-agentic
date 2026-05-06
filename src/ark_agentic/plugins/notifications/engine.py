"""Notifications engine accessor + schema initialiser.

Notifications currently shares the central ``core.storage.database`` engine
— but the feature's tables live on its own ``NotificationsBase.metadata``
and its own alembic data directory, so ``init_schema()`` here only touches
the notifications schema. A future split (dedicated DB, sharded engine)
is a one-file change.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncEngine

# Importing the storage package registers ``NotificationRow`` on
# ``NotificationsBase.metadata``.
from .storage.models import NotificationsBase


def get_engine() -> AsyncEngine:
    from ...core.storage.database.engine import get_engine as _core_get_engine
    return _core_get_engine()


async def init_schema() -> None:
    """Run alembic ``upgrade head`` for notifications tables. Idempotent."""
    from ...core.storage.database.migrate import upgrade_to_head

    await upgrade_to_head(
        metadata=NotificationsBase.metadata,
        migrations_dir=Path(__file__).parent / "storage" / "migrations",
        engine=get_engine(),
        version_table="alembic_version_notifications",
    )
