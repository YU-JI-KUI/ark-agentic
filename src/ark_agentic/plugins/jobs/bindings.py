"""Proactive job bindings — agents factory 与 core runner 的解耦桥。

模式:
  - agents factory 构造 Job + bindings
  - apply_proactive_job_bindings(runner, bindings) 通过 runner.add_warmup_hook
    把 job 注册任务挂到 runner 的 warmup 钩子上
  - runner.warmup() 触发钩子,把 job 注册进 JobManager

runner 本身不感知 Job / JobManager 的存在。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ark_agentic.core.runtime.base_agent import BaseAgent
    from .base import BaseJob

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProactiveJobBindings:
    """Resolved proactive-job binding for a runner."""

    job: "BaseJob | None" = None


def build_proactive_job_bindings(
    *, job: "BaseJob | None" = None,
) -> ProactiveJobBindings:
    """构造 bindings。job 为 None 时返回空 bindings,apply 时是 no-op。"""
    return ProactiveJobBindings(job=job)


def apply_proactive_job_bindings(
    runner: "BaseAgent",
    bindings: ProactiveJobBindings,
) -> "BaseAgent":
    """Register the job's bootstrap as a runner warmup hook.

    runner 不感知 job 类型或 JobManager;此函数负责闭包捕获 job
    并在 warmup 时动态引用 get_job_manager(允许 JobManager 未启用)。
    """
    if bindings.job is None:
        return runner

    job = bindings.job

    async def _register_proactive_job() -> None:
        try:
            from .manager import get_job_manager
        except ImportError:
            logger.debug(
                "apscheduler not installed; skipping proactive job registration "
                "for '%s'",
                job.meta.job_id,
            )
            return
        job_manager = get_job_manager()
        if job_manager is None:
            logger.debug(
                "JobManager not initialized; skipping registration for '%s'",
                job.meta.job_id,
            )
            return
        job_manager.register(job)
        logger.info("Registered proactive job '%s'", job.meta.job_id)

    runner.add_warmup_hook(_register_proactive_job)
    return runner
