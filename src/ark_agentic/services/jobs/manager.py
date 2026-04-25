"""JobManager — 统一调度器

职责：
  - 注册/管理多个 BaseJob 实例
  - 通过 APScheduler AsyncIOScheduler 按 cron 触发
  - 支持手动触发（dispatch）
  - lifespan start/stop
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

if TYPE_CHECKING:
    from ..notifications.delivery import NotificationDelivery
    from ..notifications.store import NotificationStore
    from .base import BaseJob
    from .scanner import UserShardScanner

logger = logging.getLogger(__name__)

# 全局单例：app.py 启动时设置，AgentRunner.warmup() 时取用
_global_job_manager: "JobManager | None" = None


def get_job_manager() -> "JobManager | None":
    """返回全局 JobManager 实例，未初始化时返回 None。"""
    return _global_job_manager


def set_job_manager(manager: "JobManager") -> None:
    """由 app.py lifespan 设置全局实例。"""
    global _global_job_manager
    _global_job_manager = manager


class JobManager:
    """统一 Job 调度管理器"""

    def __init__(
        self,
        notification_store: "NotificationStore",
        delivery: "NotificationDelivery",
        scanner: "UserShardScanner",
    ) -> None:
        self._store = notification_store
        self._delivery = delivery
        self._scanner = scanner
        self._jobs: dict[str, "BaseJob"] = {}
        self._scheduler = AsyncIOScheduler()

    def register(self, job: "BaseJob") -> None:
        """注册一个 Job。"""
        if not job.meta.enabled:
            logger.info("Job %s is disabled, skipping registration", job.meta.job_id)
            return

        self._jobs[job.meta.job_id] = job

        # 注册到 APScheduler
        self._scheduler.add_job(
            self._run_job,
            trigger=CronTrigger.from_crontab(job.meta.cron),
            args=[job.meta.job_id],
            id=job.meta.job_id,
            name=f"Job[{job.meta.job_id}]",
            replace_existing=True,
            max_instances=1,        # 防止上一次未完成时重复触发
            coalesce=True,          # 错过的触发合并为一次
        )
        logger.info(
            "Registered job '%s' with cron='%s'",
            job.meta.job_id,
            job.meta.cron,
        )

    async def start(self) -> None:
        """启动调度器（在 FastAPI lifespan 中调用，需在所有 agent warmup 之后）。"""
        self._scheduler.start()
        logger.info("JobManager started with jobs: %s", list(self._jobs.keys()))

    async def stop(self) -> None:
        """停止调度器（在 FastAPI lifespan 结束时调用）。"""
        self._scheduler.shutdown(wait=False)
        logger.info("JobManager stopped")

    async def dispatch(self, job_id: str) -> None:
        """手动立即触发某个 Job（供管理 API 或测试使用）。"""
        if job_id not in self._jobs:
            raise KeyError(f"Job '{job_id}' not registered")
        await self._run_job(job_id)

    async def list_jobs(self) -> list[dict]:
        """返回所有已注册 Job 的基本信息。"""
        result = []
        for job_id, job in self._jobs.items():
            scheduler_job = self._scheduler.get_job(job_id)
            result.append({
                "job_id": job_id,
                "cron": job.meta.cron,
                "enabled": job.meta.enabled,
                "next_run": str(scheduler_job.next_run_time) if scheduler_job else None,
            })
        return result

    async def _run_job(self, job_id: str) -> None:
        """实际执行 Job 的入口（由 APScheduler 或 dispatch 调用）。"""
        job = self._jobs.get(job_id)
        if not job:
            logger.error("Job %s not found", job_id)
            return

        logger.info("Starting job '%s'", job_id)
        try:
            stats = await self._scanner.scan(job, self._delivery)
            logger.info("Job '%s' completed: %s", job_id, stats.summary())
        except Exception as e:
            logger.error("Job '%s' failed: %s", job_id, e, exc_info=True)
