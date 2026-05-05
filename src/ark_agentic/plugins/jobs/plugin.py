"""JobsPlugin — built-in proactive job manager + scanner.

Requires the notifications plugin to be enabled and registered before
it (jobs broadcast through the notifications delivery channel). Reads
JOB_* env vars for scanner sizing.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ...core.protocol.plugin import BasePlugin
from ...core.storage import mode
from ...core.utils.env import env_flag

if TYPE_CHECKING:
    from .manager import JobManager
    from .scanner import UserShardScanner

logger = logging.getLogger(__name__)


@dataclass
class JobsContext:
    """Runtime state attached to ``AppContext.jobs`` by the plugin."""

    manager: "JobManager"
    scanner: "UserShardScanner"


class JobsPlugin(BasePlugin):
    """Proactive job scheduling + scanning."""

    name = "jobs"

    def __init__(self) -> None:
        self._manager: "JobManager | None" = None

    def is_enabled(self) -> bool:
        return env_flag("ENABLE_JOB_MANAGER")

    async def init(self) -> None:
        if not mode.is_database():
            return
        from .engine import init_schema
        await init_schema()

    async def start(self, ctx: Any) -> JobsContext:
        if getattr(ctx, "notifications", None) is None:
            raise RuntimeError(
                "JobsPlugin requires NotificationsPlugin to be enabled "
                "and registered before it in the components list."
            )

        try:
            from .manager import JobManager, set_job_manager
            from .scanner import UserShardScanner
        except ImportError as e:
            raise RuntimeError(
                "JobsPlugin requires 'ark-agentic[server]' (apscheduler). "
                f"Install with: pip install 'ark-agentic[server]' (cause: {e})"
            ) from e

        scanner = UserShardScanner(
            max_concurrent=int(os.getenv("JOB_MAX_CONCURRENT", "50")),
            batch_size=int(os.getenv("JOB_BATCH_SIZE", "500")),
            shard_index=int(os.getenv("JOB_SHARD_INDEX", "0")),
            total_shards=int(os.getenv("JOB_TOTAL_SHARDS", "1")),
        )
        manager = JobManager(
            delivery=ctx.notifications.service.delivery,
            scanner=scanner,
        )
        set_job_manager(manager)

        # Per-agent proactive job bindings: AgentsLifecycle starts before
        # JobsPlugin in the default component list so ctx.agent_registry
        # is always populated by the time JobsPlugin.start runs.
        from ..notifications.paths import get_notifications_base_dir
        from .proactive_setup import register_proactive_jobs
        register_proactive_jobs(
            ctx.agent_registry,
            notifications_base_dir=get_notifications_base_dir(),
        )

        await manager.start()
        logger.info("JobManager started")
        self._manager = manager
        return JobsContext(manager=manager, scanner=scanner)

    async def stop(self) -> None:
        if self._manager is not None:
            await self._manager.stop()
            logger.info("JobManager stopped")
            self._manager = None
