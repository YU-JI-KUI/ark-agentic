"""SqliteNotificationRepository — atomic mark_read via row-level locks.

Per-agent isolation lives on the row (``notifications.agent_id``); each
repository instance is bound to a single ``agent_id`` and scopes every
query/insert by it. This matches the file backend's per-agent directory
layout while letting all rows share one table.

DB row-level locking on ``UPDATE ... WHERE id IN (...)`` replaces the file
lock + read-modify-write dance from the file backend.

``list_recent`` pushes ORDER BY / WHERE / LIMIT / OFFSET into SQL so that
hot paths only materialise the page being returned, not the whole per-user
notification history. Total / unread counts are two cheap COUNT(*) queries.
"""

from __future__ import annotations

import json

from sqlalchemy import func, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncEngine

from ..models import Notification, NotificationList
from .models import NotificationRow


class SqliteNotificationRepository:
    """NotificationRepository over a SQLAlchemy AsyncEngine, scoped to one agent."""

    def __init__(self, engine: AsyncEngine, agent_id: str = "") -> None:
        self._engine = engine
        self._agent_id = agent_id

    async def save(self, notification: Notification) -> None:
        if notification.agent_id and notification.agent_id != self._agent_id:
            raise ValueError(
                f"Notification.agent_id={notification.agent_id!r} does not "
                f"match repository agent_id={self._agent_id!r}"
            )
        payload = notification.model_dump_json()
        stmt = sqlite_insert(NotificationRow).values(
            notification_id=notification.notification_id,
            agent_id=self._agent_id,
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
        scope = (
            (NotificationRow.agent_id == self._agent_id)
            & (NotificationRow.user_id == user_id)
        )

        page_stmt = (
            select(NotificationRow.payload_json, NotificationRow.read)
            .where(scope)
        )
        if unread_only:
            page_stmt = page_stmt.where(NotificationRow.read.is_(False))
        page_stmt = page_stmt.order_by(NotificationRow.created_at.desc())
        if limit:
            page_stmt = page_stmt.limit(limit).offset(offset)
        elif offset:
            page_stmt = page_stmt.limit(-1).offset(offset)

        total_stmt = (
            select(func.count()).select_from(NotificationRow).where(scope)
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
                    NotificationRow.agent_id == self._agent_id,
                    NotificationRow.user_id == user_id,
                    NotificationRow.notification_id.in_(notification_ids),
                )
                .values(read=True)
            )
