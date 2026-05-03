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
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...core.storage.protocols import (
        AgentStateRepository,
        MemoryRepository,
        NotificationRepository,
    )
    from ..notifications.delivery import NotificationDelivery
    from .base import BaseJob, JobRunStats

logger = logging.getLogger(__name__)


def _chunks(lst: list, n: int):
    """将列表切分为最大 n 个元素的子列表。"""
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


class UserShardScanner:
    """大规模用户分片扫描器

    不持有全局 MemoryManager——每次 scan() 时从 job.memory_manager 取，
    这样每个 Agent 的 Job 都能正确扫到自己的子目录：
      insurance job → data/ark_memory/insurance/{user_id}/MEMORY.md
      securities job → data/ark_memory/securities/{user_id}/MEMORY.md
    """

    def __init__(
        self,
        max_concurrent: int = 50,
        batch_size: int = 500,
        user_timeout: float = 30.0,
        shard_index: int = 0,
        total_shards: int = 1,
    ) -> None:
        self._max_concurrent = max_concurrent
        self._batch_size = batch_size
        self._user_timeout = user_timeout
        self._shard_index = shard_index
        self._total_shards = total_shards

    async def scan(
        self,
        job: "BaseJob",
        delivery: "NotificationDelivery",
        notification_repo: "NotificationRepository | None" = None,
    ) -> "JobRunStats":
        """Scan all users; for users with intent, run the job's full pipeline."""
        from ...core.storage.factory import (
            build_agent_state_repository,
            build_memory_repository,
        )
        from .base import JobRunStats

        stats = JobRunStats()
        semaphore = asyncio.Semaphore(self._max_concurrent)

        # Prefer the Job's per-agent NotificationRepository; the parameter
        # is a test-time injection escape hatch.
        effective_repo = notification_repo or job.notification_repo

        # Repositories rooted at job's per-agent memory workspace.
        # Backend selected by ``DB_TYPE`` via the storage factory.
        engine = getattr(job, "db_engine", None)
        workspace_dir = job.memory_manager.config.workspace_dir
        memory_repo: MemoryRepository = build_memory_repository(
            workspace_dir=workspace_dir, engine=engine,
        )
        state_repo: AgentStateRepository = build_agent_state_repository(
            workspace_dir=workspace_dir,
            engine=engine,
        )

        # list_users via MemoryRepository (替代 iterdir + 逐用户 stat 风暴)
        all_users = await memory_repo.list_users(order_by_updated_desc=True)
        # 分片过滤（水平扩展时每个实例只处理自己的分片）
        if self._total_shards > 1:
            all_users = [
                u for u in all_users
                if hash(u) % self._total_shards == self._shard_index
            ]
        stats.scanned = len(all_users)
        logger.info("Job %s: scanning %d users (shard %d/%d)", job.meta.job_id, len(all_users), self._shard_index + 1, self._total_shards)

        async def _process_one(user_id: str) -> None:
            async with semaphore:
                await self._process_user_safe(
                    user_id, job, effective_repo, delivery, stats, state_repo,
                )

        for batch in _chunks(all_users, self._batch_size):
            tasks = [_process_one(uid) for uid in batch]
            await asyncio.gather(*tasks, return_exceptions=True)
            # 批次间让出控制权，避免长时间独占事件循环
            await asyncio.sleep(0)

        logger.info("Job %s done: %s", job.meta.job_id, stats.summary())
        return stats

    async def _process_user_safe(
        self,
        user_id: str,
        job: "BaseJob",
        repo: "NotificationRepository",
        delivery: "NotificationDelivery",
        stats: "JobRunStats",
        state_repo: "AgentStateRepository",
    ) -> None:
        """Per-user pipeline with timeout + exception isolation."""
        try:
            memory = await job.memory_manager.read_memory(user_id)
            if not memory:
                stats.skipped += 1
                return

            # Phase 1: cheap keyword filter (<1ms, no LLM)
            if not await job.should_process_user(user_id, memory):
                stats.skipped += 1
                return

            # Idempotency: already processed today → skip.
            if await self._is_already_processed_today(user_id, job, state_repo):
                stats.skipped += 1
                return

            # Phase 2: full pipeline (LLM + tool calls)
            async with asyncio.timeout(self._user_timeout):
                notifications = await job.process_user(user_id, memory)

            if notifications:
                result = await delivery.broadcast(notifications, repo)
                stats.notified += 1
                stats.pushed += result.get("pushed", 0)
                stats.stored += result.get("stored", 0)
            else:
                stats.skipped += 1

            await self._touch_last_job(user_id, job, state_repo)

        except asyncio.TimeoutError:
            stats.timed_out += 1
            logger.warning("Job %s timed out for user %s", job.meta.job_id, user_id)
        except Exception as e:
            stats.errors += 1
            logger.error("Job %s error for user %s: %s", job.meta.job_id, user_id, e, exc_info=True)

    @staticmethod
    def _job_state_key(job: "BaseJob") -> str:
        return f"last_job_{job.meta.job_id}"

    async def _is_already_processed_today(
        self,
        user_id: str,
        job: "BaseJob",
        state_repo: "AgentStateRepository",
    ) -> bool:
        """检查今天是否已经处理过（防止 Job 重启后重复处理）。"""
        raw = await state_repo.get(user_id, self._job_state_key(job))
        if raw is None:
            return False
        try:
            last_ts = float(raw.strip())
            # 24 小时内已处理视为重复
            return (time.time() - last_ts) < 86400
        except (ValueError, AttributeError):
            return False

    async def _touch_last_job(
        self,
        user_id: str,
        job: "BaseJob",
        state_repo: "AgentStateRepository",
    ) -> None:
        """写入当前时间戳作为最后处理时间。"""
        try:
            await state_repo.set(
                user_id, self._job_state_key(job), str(time.time())
            )
        except OSError as e:
            logger.warning("Failed to touch last_job for %s: %s", user_id, e)
