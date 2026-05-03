"""SqliteNotificationRepository — atomic mark_read via row-level locks.

DB row-level locking on UPDATE ... WHERE id IN (...) replaces the file lock +
read-modify-write dance from the file backend.

``list_recent`` pushes ORDER BY / WHERE / LIMIT / OFFSET down into SQL so that
hot paths only materialise the page being returned, not the whole per-user
notification history. Total / unread counts are two cheap COUNT(*) queries.
"""

from __future__ import annotations

import json

from sqlalchemy import func, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
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
        # ON CONFLICT DO NOTHING keeps save() idempotent on retries without
        # the SELECT-then-INSERT race.
        stmt = sqlite_insert(NotificationRow).values(
            notification_id=notification.notification_id,
            user_id=notification.user_id,
            payload_json=payload,
            read=notification.read,
            created_at=notification.created_at,
        ).on_conflict_do_nothing(index_elements=["notification_id"])
        async with self._engine.begin() as conn:
            await conn.execute(stmt)

    async def list_recent(
        self,
        user_id: str,
        limit: int = 50,
        offset: int = 0,
        unread_only: bool = False,
    ) -> NotificationList:
        # Page query — only the rows we'll actually return cross the wire.
        page_stmt = (
            select(NotificationRow.payload_json, NotificationRow.read)
            .where(NotificationRow.user_id == user_id)
        )
        if unread_only:
            page_stmt = page_stmt.where(NotificationRow.read.is_(False))
        page_stmt = page_stmt.order_by(NotificationRow.created_at.desc())
        if limit:
            page_stmt = page_stmt.limit(limit).offset(offset)
        elif offset:
            # SQLAlchemy requires LIMIT for OFFSET; use -1 (no bound).
            page_stmt = page_stmt.limit(-1).offset(offset)

        # Count queries — independent of paging / unread_only filter so the
        # response shape matches the file backend (total reflects the user's
        # full visible set, unread_count is the live unread tally).
        total_stmt = (
            select(func.count())
            .select_from(NotificationRow)
            .where(NotificationRow.user_id == user_id)
        )
        unread_stmt = total_stmt.where(NotificationRow.read.is_(False))

        async with self._engine.connect() as conn:
            page_rows = (await conn.execute(page_stmt)).all()
            total = (await conn.execute(total_stmt)).scalar_one()
            unread_count = (await conn.execute(unread_stmt)).scalar_one()

        notifications: list[Notification] = []
        for payload_json, read_flag in page_rows:
            data = json.loads(payload_json)
            data["read"] = bool(read_flag)
            notifications.append(Notification(**data))

        return NotificationList(
            notifications=notifications,
            total=int(total),
            unread_count=int(unread_count),
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
