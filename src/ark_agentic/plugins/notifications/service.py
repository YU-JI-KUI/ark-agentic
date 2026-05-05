"""NotificationsService — 业务层，统一封装 repo + delivery。

目的：API handler 与 scanner 不再直接接触 ``NotificationRepository``；
存储层（per-agent repo cache）+ 实时分发层（SSE queue）的细节都收敛到
本类内部。

公共方法对应两类调用方：
- API handler（拉历史 / 标已读 / SSE 注册）
- 任何生产通知的代码（scanner / proactive jobs）

存储后端（file / sqlite）由 ``DB_TYPE`` 在 ``build_notification_repository``
内部决定，service 不感知。
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from .delivery import NotificationDelivery
from .factory import build_notification_repository
from .models import Notification, NotificationList
from .protocol import NotificationRepository

logger = logging.getLogger(__name__)


class NotificationsService:
    """Business layer for the notifications feature.

    Owns:
      - per-agent ``NotificationRepository`` cache (lazy build)
      - the ``NotificationDelivery`` instance (SSE pub/sub)

    The ``base_dir`` argument is the file-mode root containing per-agent
    subdirectories; SQLite mode ignores it but we keep the parameter
    for parity with file-mode call sites.
    """

    def __init__(
        self,
        base_dir: Path,
        delivery: NotificationDelivery | None = None,
    ) -> None:
        self._base_dir = base_dir
        self._delivery = delivery or NotificationDelivery()
        self._repos: dict[str, NotificationRepository] = {}

    # ── Internal: per-agent repo resolution ─────────────────────────

    def _repo_for(self, agent_id: str) -> NotificationRepository:
        repo = self._repos.get(agent_id)
        if repo is None:
            repo = build_notification_repository(
                base_dir=self._base_dir / agent_id,
                agent_id=agent_id,
            )
            self._repos[agent_id] = repo
        return repo

    # ── Read-side API (HTTP handlers) ───────────────────────────────

    async def list_for_user(
        self,
        agent_id: str,
        user_id: str,
        *,
        limit: int = 50,
        unread_only: bool = False,
    ) -> NotificationList:
        return await self._repo_for(agent_id).list_recent(
            user_id, limit=limit, unread_only=unread_only,
        )

    async def mark_read(
        self,
        agent_id: str,
        user_id: str,
        notification_ids: list[str],
    ) -> None:
        await self._repo_for(agent_id).mark_read(user_id, notification_ids)

    async def unread_count(self, agent_id: str, user_id: str) -> int:
        result = await self._repo_for(agent_id).list_recent(
            user_id, limit=1, unread_only=True,
        )
        return result.unread_count

    # ── SSE registration (HTTP handlers) ────────────────────────────

    def _stream_key(self, agent_id: str, user_id: str) -> str:
        return f"{agent_id}:{user_id}" if agent_id else user_id

    def register_stream(
        self, agent_id: str, user_id: str, queue: asyncio.Queue,
    ) -> None:
        self._delivery.register_user_online(
            self._stream_key(agent_id, user_id), queue,
        )

    def unregister_stream(self, agent_id: str, user_id: str) -> None:
        self._delivery.unregister_user(self._stream_key(agent_id, user_id))

    # ── Write-side API (scanner / proactive producers) ──────────────

    async def deliver(self, notification: Notification) -> bool:
        """Store + try real-time push for a single notification."""
        return await self._delivery.deliver(
            notification, self._repo_for(notification.agent_id),
        )

    async def broadcast(
        self, notifications: list[Notification],
    ) -> dict[str, int]:
        """Store + try real-time push for many notifications, grouped by
        agent_id internally so each repo is reused across the batch."""
        pushed = 0
        stored = 0
        for n in notifications:
            if await self.deliver(n):
                pushed += 1
            else:
                stored += 1
        return {"pushed": pushed, "stored": stored}

    # ── Test / advanced inspection ──────────────────────────────────

    @property
    def delivery(self) -> NotificationDelivery:
        """Direct access for tests + scanner callbacks that still want it.
        Production handlers should use the typed methods above."""
        return self._delivery
