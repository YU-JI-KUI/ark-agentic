"""FileNotificationRepository — file-backed NotificationRepository.

Owns all file I/O. Layout per agent (caller pre-scopes ``base_dir`` to
``{notifications_root}/{agent_id}``):

  ``{base_dir}/{user_id}/notifications.jsonl``  — one JSON per line
  ``{base_dir}/{user_id}/.read_ids``            — read notification_id set

Concurrency: ``mark_read`` is read-modify-write so each user has its own
``asyncio.Lock`` guarding that critical section.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from ..models import Notification, NotificationList

logger = logging.getLogger(__name__)

_MAX_TAIL_LINES = 200


class FileNotificationRepository:
    """File-backed implementation of NotificationRepository."""

    def __init__(self, base_dir: str | Path) -> None:
        self._base_dir = Path(base_dir)
        self._base_dir.mkdir(parents=True, exist_ok=True)

        self._user_locks: dict[str, asyncio.Lock] = {}
        self._locks_lock = asyncio.Lock()

    # ── Path helpers ────────────────────────────────────────────────

    def _user_dir(self, user_id: str) -> Path:
        return self._base_dir / user_id

    def _jsonl_path(self, user_id: str) -> Path:
        return self._user_dir(user_id) / "notifications.jsonl"

    def _read_ids_path(self, user_id: str) -> Path:
        return self._user_dir(user_id) / ".read_ids"

    async def _get_user_lock(self, user_id: str) -> asyncio.Lock:
        async with self._locks_lock:
            return self._user_locks.setdefault(user_id, asyncio.Lock())

    # ── Protocol methods ────────────────────────────────────────────

    async def save(self, notification: Notification) -> None:
        await asyncio.to_thread(self._save_sync, notification)

    async def list_recent(
        self,
        user_id: str,
        limit: int = 50,
        offset: int = 0,
        unread_only: bool = False,
    ) -> NotificationList:
        # File 实现忽略 offset (SQLite uses LIMIT/OFFSET pushdown).
        return await asyncio.to_thread(
            self._list_recent_sync, user_id, limit, unread_only,
        )

    async def mark_read(
        self, user_id: str, notification_ids: list[str],
    ) -> None:
        if not notification_ids:
            return
        lock = await self._get_user_lock(user_id)
        async with lock:
            await asyncio.to_thread(
                self._mark_read_sync, user_id, notification_ids,
            )

    # ── Sync internals (run via asyncio.to_thread) ──────────────────

    def _save_sync(self, notification: Notification) -> None:
        path = self._jsonl_path(notification.user_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(notification.model_dump_json() + "\n")
        logger.debug(
            "Saved notification %s for user %s",
            notification.notification_id, notification.user_id,
        )

    def _list_recent_sync(
        self, user_id: str, limit: int, unread_only: bool,
    ) -> NotificationList:
        path = self._jsonl_path(user_id)
        if not path.exists():
            return NotificationList(
                notifications=[], total=0, unread_count=0,
            )

        read_ids = self._load_read_ids(user_id)
        lines = self._tail_lines(path, _MAX_TAIL_LINES)
        notifications: list[Notification] = []
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                n = Notification(**data)
                n.read = n.notification_id in read_ids
                notifications.append(n)
            except Exception:
                continue

        total = len(notifications)
        unread_count = sum(1 for n in notifications if not n.read)

        if unread_only:
            notifications = [n for n in notifications if not n.read]
        notifications = notifications[:limit]
        return NotificationList(
            notifications=notifications,
            total=total,
            unread_count=unread_count,
        )

    def _mark_read_sync(
        self, user_id: str, notification_ids: list[str],
    ) -> None:
        path = self._read_ids_path(user_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        merged = self._load_read_ids(user_id) | set(notification_ids)
        path.write_text("\n".join(merged), encoding="utf-8")

    def _load_read_ids(self, user_id: str) -> set[str]:
        path = self._read_ids_path(user_id)
        if not path.exists():
            return set()
        try:
            return {
                line.strip()
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            }
        except OSError:
            return set()

    @staticmethod
    def _tail_lines(path: Path, n: int) -> list[str]:
        """Return up to the last ``n`` lines from ``path``."""
        try:
            with path.open("r", encoding="utf-8") as f:
                lines = f.readlines()
        except OSError:
            return []
        return lines[-n:] if len(lines) > n else lines
