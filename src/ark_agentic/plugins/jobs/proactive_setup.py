"""Proactive job wiring — binds agent-specific jobs to their runners.

Called once during app lifespan after agents are registered and before
the JobManager starts. Keeps app.py thin: all per-agent job construction
lives here.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ark_agentic.core.runtime.registry import AgentRegistry


def register_proactive_jobs(
    registry: "AgentRegistry",
    *,
    notifications_base_dir: Path,
) -> None:
    """Bind proactive jobs for all agents that have a memory manager."""
    from ark_agentic.plugins.jobs import (
        apply_proactive_job_bindings,
        build_proactive_job_bindings,
    )
    from ark_agentic.plugins.notifications import build_notification_repository
    from ark_agentic.agents.insurance.proactive_job import InsuranceProactiveJob
    from ark_agentic.agents.securities.proactive_job import SecuritiesProactiveJob

    def _notif_repo(agent_id: str):
        return build_notification_repository(
            base_dir=notifications_base_dir / agent_id,
            agent_id=agent_id,
        )

    ins_runner = registry.get("insurance")
    if ins_runner.memory_manager is not None:
        apply_proactive_job_bindings(
            ins_runner,
            build_proactive_job_bindings(job=InsuranceProactiveJob(
                job_id="proactive_service_insurance",
                llm_factory=lambda: ins_runner.llm,
                tool_registry=ins_runner.tool_registry,
                memory_manager=ins_runner.memory_manager,
                notification_repo=_notif_repo("insurance"),
                cron=os.getenv("INSURANCE_PROACTIVE_CRON", "26 23 * * *"),
            )),
        )

    sec_runner = registry.get("securities")
    if sec_runner.memory_manager is not None:
        apply_proactive_job_bindings(
            sec_runner,
            build_proactive_job_bindings(job=SecuritiesProactiveJob(
                job_id="proactive_service_securities",
                llm_factory=lambda: sec_runner.llm,
                tool_registry=sec_runner.tool_registry,
                memory_manager=sec_runner.memory_manager,
                notification_repo=_notif_repo("securities"),
                cron=os.getenv("SECURITIES_PROACTIVE_CRON", "0 9 * * 1-5"),
            )),
        )
