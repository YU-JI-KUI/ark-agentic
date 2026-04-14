"""UserShardScanner — 大规模用户分片扫描器

核心设计：
  1. 目录列举放线程池（避免阻塞 asyncio 事件循环）
  2. 按 MEMORY.md mtime 倒序（活跃用户优先处理）
  3. asyncio.Semaphore 控制并发（不超过 max_concurrent_users）
  4. 分批 asyncio.gather（每批 batch_size 个用户并行）
  5. 幂等保护：.last_job_{job_id} 文件记录上次执行时间
  6. 支持分片：hash(user_id) % total_shards == shard_index（水平扩展用）
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..memory.manager import MemoryManager
    from ..notifications.delivery import NotificationDelivery
    from ..notifications.store import NotificationStore
    from .base import BaseJob, JobRunStats

logger = logging.getLogger(__name__)


def _chunks(lst: list, n: int):
    """将列表切分为最大 n 个元素的子列表。"""
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


class UserShardScanner:
    """大规模用户分片扫描器"""

    def __init__(
        self,
        memory_manager: "MemoryManager",
        max_concurrent: int = 50,
        batch_size: int = 500,
        user_timeout: float = 30.0,
        shard_index: int = 0,
        total_shards: int = 1,
    ) -> None:
        self._memory_manager = memory_manager
        self._max_concurrent = max_concurrent
        self._batch_size = batch_size
        self._user_timeout = user_timeout
        self._shard_index = shard_index
        self._total_shards = total_shards

    async def scan(
        self,
        job: "BaseJob",
        store: "NotificationStore",
        delivery: "NotificationDelivery",
    ) -> "JobRunStats":
        """扫描所有用户，对有意图的用户调用 Job 处理逻辑。"""
        from .base import JobRunStats

        stats = JobRunStats()
        semaphore = asyncio.Semaphore(self._max_concurrent)

        memory_base = Path(self._memory_manager.config.workspace_dir)

        # 目录列举放线程池，避免阻塞事件循环
        all_users = await asyncio.to_thread(self._list_and_sort_users, memory_base)
        stats.scanned = len(all_users)
        logger.info("Job %s: scanning %d users (shard %d/%d)", job.meta.job_id, len(all_users), self._shard_index + 1, self._total_shards)

        async def _process_one(user_id: str) -> None:
            async with semaphore:
                await self._process_user_safe(user_id, job, store, delivery, stats)

        for batch in _chunks(all_users, self._batch_size):
            tasks = [_process_one(uid) for uid in batch]
            await asyncio.gather(*tasks, return_exceptions=True)
            # 批次间让出控制权，避免长时间独占事件循环
            await asyncio.sleep(0)

        logger.info("Job %s done: %s", job.meta.job_id, stats.summary())
        return stats

    def _list_and_sort_users(self, base: Path) -> list[str]:
        """列举所有有 MEMORY.md 的用户目录，按 mtime 倒序（活跃用户优先）。

        若启用了分片，只返回属于本 shard 的用户。
        """
        if not base.exists():
            return []

        try:
            entries = [
                d for d in base.iterdir()
                if d.is_dir() and (d / "MEMORY.md").exists()
            ]
        except OSError as e:
            logger.error("Failed to list user directories: %s", e)
            return []

        # 分片过滤（水平扩展时每个实例只处理自己的分片）
        if self._total_shards > 1:
            entries = [d for d in entries if hash(d.name) % self._total_shards == self._shard_index]

        # 按 MEMORY.md 最后修改时间倒序（近期活跃用户优先）
        entries.sort(
            key=lambda d: (d / "MEMORY.md").stat().st_mtime,
            reverse=True,
        )
        return [d.name for d in entries]

    async def _process_user_safe(
        self,
        user_id: str,
        job: "BaseJob",
        store: "NotificationStore",
        delivery: "NotificationDelivery",
        stats: "JobRunStats",
    ) -> None:
        """带超时、异常隔离的单用户处理。"""
        try:
            memory = self._memory_manager.read_memory(user_id)
            if not memory:
                stats.skipped += 1
                return

            # 阶段1：轻量规则过滤（<1ms，无 LLM）
            if not await job.should_process_user(user_id, memory):
                stats.skipped += 1
                return

            # 幂等检查：本次 Job 运行已处理过此用户则跳过
            if self._is_already_processed_today(user_id, job.meta.job_id):
                stats.skipped += 1
                return

            # 阶段2：完整处理（LLM + 工具调用）
            async with asyncio.timeout(self._user_timeout):
                notifications = await job.process_user(user_id, memory)

            if notifications:
                result = await delivery.broadcast(notifications, store)
                stats.notified += 1
                stats.pushed += result.get("pushed", 0)
                stats.stored += result.get("stored", 0)
            else:
                stats.skipped += 1

            # 更新处理时间戳（幂等保护）
            self._touch_last_job(user_id, job.meta.job_id)

        except asyncio.TimeoutError:
            stats.timed_out += 1
            logger.warning("Job %s timed out for user %s", job.meta.job_id, user_id)
        except Exception as e:
            stats.errors += 1
            logger.error("Job %s error for user %s: %s", job.meta.job_id, user_id, e, exc_info=True)

    def _last_job_path(self, user_id: str, job_id: str) -> Path:
        base = Path(self._memory_manager.config.workspace_dir)
        return base / user_id / f".last_job_{job_id}"

    def _is_already_processed_today(self, user_id: str, job_id: str) -> bool:
        """检查今天是否已经处理过（防止 Job 重启后重复处理）。"""
        p = self._last_job_path(user_id, job_id)
        if not p.exists():
            return False
        try:
            last_ts = float(p.read_text(encoding="utf-8").strip())
            # 24 小时内已处理视为重复
            return (time.time() - last_ts) < 86400
        except (ValueError, OSError):
            return False

    def _touch_last_job(self, user_id: str, job_id: str) -> None:
        """写入当前时间戳作为最后处理时间。"""
        p = self._last_job_path(user_id, job_id)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(str(time.time()), encoding="utf-8")
        except OSError as e:
            logger.warning("Failed to touch last_job file for %s: %s", user_id, e)
