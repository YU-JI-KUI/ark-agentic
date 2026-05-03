"""NotificationRepository Protocol — async notification storage."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ....services.notifications.models import Notification, NotificationList


@runtime_checkable
class NotificationRepository(Protocol):
    """Per-user notification storage."""

    async def save(self, notification: Notification) -> None:
        ...

    async def list_recent(
        self,
        user_id: str,
        limit: int = 50,
        offset: int = 0,
        unread_only: bool = False,
    ) -> NotificationList:
        """offset 是为 PR2 DB 实现预留的翻页扩展点；File 实现忽略。"""
        ...

    async def mark_read(self, user_id: str, notification_ids: list[str]) -> None:
        """File 实现：file lock + read-modify-write (修复现有竞态)。
        DB 实现：UPDATE notifications SET read=TRUE WHERE notification_id IN (?)。"""
        ...
