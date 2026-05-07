"""Proactive job wiring — registers per-agent jobs with the JobManager.

Called once from ``JobsPlugin.start()`` after agents are registered and
the JobManager is constructed. Keeps app.py thin: all per-agent job
construction lives here.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ark_agentic.core.runtime.registry import AgentRegistry
    from .manager import JobManager


def register_proactive_jobs(
    registry: "AgentRegistry",
    manager: "JobManager",
    *,
    notifications_base_dir: Path,
) -> None:
    """Build proactive jobs for memory-enabled agents and register them.

    Registers directly into the supplied ``JobManager``. No indirection
    via runner warmup hooks — JobsPlugin owns the agent → job binding
    decision and the manager is the single source of scheduling truth.
    """
    from ark_agentic.plugins.notifications import build_notification_repository
    from ark_agentic.agents.insurance.proactive_job import InsuranceProactiveJob
    from ark_agentic.agents.securities.proactive_job import SecuritiesProactiveJob

    def _notif_repo(agent_id: str):
        return build_notification_repository(
            base_dir=notifications_base_dir / agent_id,
            agent_id=agent_id,
        )

    if "insurance" in registry.list_ids():
        ins = registry.get("insurance")
        if ins.memory_manager is not None:
            manager.register(InsuranceProactiveJob(
                job_id="proactive_service_insurance",
                llm_factory=lambda: ins.llm,
                tool_registry=ins.tool_registry,
                memory_manager=ins.memory_manager,
                notification_repo=_notif_repo("insurance"),
                cron=os.getenv("INSURANCE_PROACTIVE_CRON", "26 23 * * *"),
            ))

    if "securities" in registry.list_ids():
        sec = registry.get("securities")
        if sec.memory_manager is not None:
            manager.register(SecuritiesProactiveJob(
                job_id="proactive_service_securities",
                llm_factory=lambda: sec.llm,
                tool_registry=sec.tool_registry,
                memory_manager=sec.memory_manager,
                notification_repo=_notif_repo("securities"),
                cron=os.getenv("SECURITIES_PROACTIVE_CRON", "0 9 * * 1-5"),
            ))
