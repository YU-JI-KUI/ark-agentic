"""通知持久化 — JSONL 文件存储

设计：与现有 persistence.py 风格一致，纯文件，无数据库依赖。

目录结构：
  {base_dir}/{user_id}/notifications.jsonl   ← 通知追加写，每行一条 JSON
  {base_dir}/{user_id}/.read_ids             ← 已读 notification_id 集合（每行一个 ID）
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from .models import Notification, NotificationList

logger = logging.getLogger(__name__)

# 单次最多读取的行数（防止超大文件全量加载）
_MAX_READ_LINES = 200


class NotificationStore:
    def __init__(self, base_dir: Path) -> None:
        self._base_dir = base_dir
        self._base_dir.mkdir(parents=True, exist_ok=True)

    # ── 路径辅助 ──────────────────────────────────────────────

    def _user_dir(self, user_id: str) -> Path:
        return self._base_dir / user_id

    def _jsonl_path(self, user_id: str) -> Path:
        return self._user_dir(user_id) / "notifications.jsonl"

    def _read_ids_path(self, user_id: str) -> Path:
        return self._user_dir(user_id) / ".read_ids"

    # ── 写入 ──────────────────────────────────────────────────

    async def save(self, notification: Notification) -> None:
        """追加写入通知到 JSONL。使用线程池避免阻塞事件循环。"""
        await asyncio.to_thread(self._save_sync, notification)

    def _save_sync(self, notification: Notification) -> None:
        p = self._jsonl_path(notification.user_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(notification.model_dump_json() + "\n")
        logger.debug("Saved notification %s for user %s", notification.notification_id, notification.user_id)

    # ── 读取 ──────────────────────────────────────────────────

    async def list_recent(
        self,
        user_id: str,
        limit: int = 50,
        unread_only: bool = False,
    ) -> NotificationList:
        """读取最近的通知（从 JSONL 尾部反向读取，避免全量加载）。"""
        return await asyncio.to_thread(self._list_recent_sync, user_id, limit, unread_only)

    def _list_recent_sync(self, user_id: str, limit: int, unread_only: bool) -> NotificationList:
        p = self._jsonl_path(user_id)
        if not p.exists():
            return NotificationList(notifications=[], total=0, unread_count=0)

        read_ids = self._load_read_ids(user_id)

        # 反向读取最近 _MAX_READ_LINES 行
        lines = self._tail_lines(p, _MAX_READ_LINES)
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
                continue  # 跳过损坏行

        total = len(notifications)
        unread_count = sum(1 for n in notifications if not n.read)

        if unread_only:
            notifications = [n for n in notifications if not n.read]

        notifications = notifications[:limit]
        return NotificationList(notifications=notifications, total=total, unread_count=unread_count)

    def _tail_lines(self, path: Path, n: int) -> list[str]:
        """从文件末尾读取最多 n 行（简单实现，适合中小文件）。"""
        try:
            with path.open("r", encoding="utf-8") as f:
                lines = f.readlines()
            return lines[-n:] if len(lines) > n else lines
        except OSError:
            return []

    # ── 已读管理 ──────────────────────────────────────────────

    async def mark_read(self, user_id: str, notification_ids: list[str]) -> None:
        """标记通知为已读。"""
        await asyncio.to_thread(self._mark_read_sync, user_id, notification_ids)

    def _mark_read_sync(self, user_id: str, notification_ids: list[str]) -> None:
        p = self._read_ids_path(user_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        existing = self._load_read_ids(user_id)
        merged = existing | set(notification_ids)
        p.write_text("\n".join(merged), encoding="utf-8")

    def _load_read_ids(self, user_id: str) -> set[str]:
        p = self._read_ids_path(user_id)
        if not p.exists():
            return set()
        try:
            return {line.strip() for line in p.read_text(encoding="utf-8").splitlines() if line.strip()}
        except OSError:
            return set()
