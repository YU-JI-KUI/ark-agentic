"""FileNotificationRepository — wraps NotificationStore.

并发修复：mark_read 自带 per-user asyncio.Lock 防止 read-modify-write 丢写。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from .....services.notifications.models import Notification, NotificationList
from .....services.notifications.store import NotificationStore


class FileNotificationRepository:
    """File-backed implementation of NotificationRepository."""

    def __init__(self, base_dir: str | Path) -> None:
        self._store = NotificationStore(Path(base_dir))
        # Per-user lock for mark_read read-modify-write critical section.
        self._user_locks: dict[str, asyncio.Lock] = {}
        self._locks_lock = asyncio.Lock()

    async def _get_user_lock(self, user_id: str) -> asyncio.Lock:
        async with self._locks_lock:
            if user_id not in self._user_locks:
                self._user_locks[user_id] = asyncio.Lock()
            return self._user_locks[user_id]

    async def save(self, notification: Notification) -> None:
        await self._store.save(notification)

    async def list_recent(
        self,
        user_id: str,
        limit: int = 50,
        offset: int = 0,
        unread_only: bool = False,
    ) -> NotificationList:
        # File 实现忽略 offset (PR2 SQLite 实现使用 LIMIT/OFFSET)
        return await self._store.list_recent(
            user_id, limit=limit, unread_only=unread_only,
        )

    async def mark_read(self, user_id: str, notification_ids: list[str]) -> None:
        lock = await self._get_user_lock(user_id)
        # asyncio.Lock 在 await to_thread() 全程持有，阻止其他协程
        # 进入临界区；与 to_thread 内部的同步执行正确串行。
        async with lock:
            await self._store.mark_read(user_id, notification_ids)
