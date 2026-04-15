"""通知分发 — 在线实时推送 + 离线持久化

策略：先落盘，再尝试推送。
  - 用户在线（有活跃 SSE 连接）：存储 + 实时推送到 asyncio.Queue
  - 用户离线：只存储，等用户下次上线时通过 REST 拉取
"""

from __future__ import annotations

import asyncio
import logging

from .models import Notification
from .store import NotificationStore

logger = logging.getLogger(__name__)

# SSE 队列最大容量，防止慢消费者积压内存
_QUEUE_MAXSIZE = 100


class NotificationDelivery:
    """单例分发中心，管理在线用户的 SSE 推送队列。"""

    def __init__(self) -> None:
        # user_id → asyncio.Queue（用户建立 SSE 连接时注册）
        self._online_queues: dict[str, asyncio.Queue] = {}

    # ── 连接管理 ──────────────────────────────────────────────

    def register_user_online(self, user_id: str, queue: asyncio.Queue) -> None:
        """用户建立 SSE 连接时调用。"""
        self._online_queues[user_id] = queue
        logger.debug("User %s connected to notification stream", user_id)

    def unregister_user(self, user_id: str) -> None:
        """用户断开 SSE 连接时调用。"""
        self._online_queues.pop(user_id, None)
        logger.debug("User %s disconnected from notification stream", user_id)

    def is_online(self, user_id: str) -> bool:
        return user_id in self._online_queues

    # ── 分发 ──────────────────────────────────────────────────

    async def deliver(self, notification: Notification, store: NotificationStore) -> bool:
        """存储通知，并尝试实时推送给在线用户。

        Returns:
            True  — 已实时推送
            False — 用户离线，仅存储
        """
        # 1. 先落盘（保证持久化，不因推送失败丢失）
        await store.save(notification)

        # 2. 尝试实时推送
        # stream_key 格式："{agent_id}:{user_id}"（与 SSE 注册时保持一致）
        # 若 agent_id 为空（旧数据兼容），退回到只用 user_id
        stream_key = (
            f"{notification.agent_id}:{notification.user_id}"
            if notification.agent_id
            else notification.user_id
        )
        queue = self._online_queues.get(stream_key)
        if queue is not None:
            try:
                queue.put_nowait({
                    "type": "new_notification",
                    "data": notification.model_dump(),
                })
                logger.debug("Pushed notification %s to online user %s", notification.notification_id, stream_key)
                return True
            except asyncio.QueueFull:
                logger.warning("Notification queue full for user %s, notification stored only", stream_key)

        return False

    async def broadcast(self, notifications: list[Notification], store: NotificationStore) -> dict[str, int]:
        """批量分发，返回 {"pushed": N, "stored": N}。"""
        pushed = 0
        stored = 0
        for n in notifications:
            if await self.deliver(n, store):
                pushed += 1
            else:
                stored += 1
        return {"pushed": pushed, "stored": stored}
