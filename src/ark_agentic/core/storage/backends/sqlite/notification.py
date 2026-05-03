"""SqliteNotificationRepository — atomic mark_read via row-level locks.

DB row-level locking on UPDATE ... WHERE id IN (...) replaces the file lock +
read-modify-write dance from the file backend.
"""

from __future__ import annotations

import json

from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from .....services.notifications.models import (
    Notification,
    NotificationList,
)
from ....db.models import NotificationRow


class SqliteNotificationRepository:
    """NotificationRepository over a SQLAlchemy AsyncEngine."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def save(self, notification: Notification) -> None:
        payload = notification.model_dump_json()
        async with self._engine.begin() as conn:
            await conn.execute(
                insert(NotificationRow).values(
                    notification_id=notification.notification_id,
                    user_id=notification.user_id,
                    payload_json=payload,
                    read=notification.read,
                    created_at=notification.created_at,
                )
            )

    async def list_recent(
        self,
        user_id: str,
        limit: int = 50,
        offset: int = 0,
        unread_only: bool = False,
    ) -> NotificationList:
        # total + unread_count baseline computed before unread_only filter so
        # the response shape matches the file backend (NotificationList.total
        # reflects the user's full visible set, not just the returned slice).
        async with self._engine.connect() as conn:
            base_rows = (await conn.execute(
                select(
                    NotificationRow.payload_json,
                    NotificationRow.read,
                )
                .where(NotificationRow.user_id == user_id)
            )).all()

        all_notifications: list[Notification] = []
        for payload_json, read_flag in base_rows:
            data = json.loads(payload_json)
            data["read"] = bool(read_flag)
            all_notifications.append(Notification(**data))

        total = len(all_notifications)
        unread_count = sum(1 for n in all_notifications if not n.read)

        # Apply ordering + filter + paging on the in-memory list. SQLite is
        # cheap enough that sub-millisecond list builds matter less than
        # behavioral parity with the file impl. PR3 PG version should push
        # ORDER BY / LIMIT down into SQL.
        all_notifications.sort(key=lambda n: n.created_at, reverse=True)
        filtered = (
            [n for n in all_notifications if not n.read]
            if unread_only
            else all_notifications
        )
        paged = filtered[offset:offset + limit] if limit else filtered[offset:]

        return NotificationList(
            notifications=paged,
            total=total,
            unread_count=unread_count,
        )

    async def mark_read(self, user_id: str, notification_ids: list[str]) -> None:
        if not notification_ids:
            return
        async with self._engine.begin() as conn:
            await conn.execute(
                update(NotificationRow)
                .where(
                    NotificationRow.user_id == user_id,
                    NotificationRow.notification_id.in_(notification_ids),
                )
                .values(read=True)
            )
