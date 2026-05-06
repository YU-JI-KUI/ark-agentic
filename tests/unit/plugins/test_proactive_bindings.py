"""Verify ``register_proactive_jobs`` directly registers per-agent jobs
into the supplied ``JobManager``.

The previous warmup-hook indirection was deleted: agents no longer carry
job-lifecycle state, and the hook chain was broken in practice (added
*after* ``AgentsLifecycle`` had finished its warmup loop). Tests cover
the new straight-line wiring.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest


def _make_registry_with_agent(agent_id: str, *, has_memory: bool) -> Any:
    registry = MagicMock()
    registry.list_ids.return_value = [agent_id]
    runner = MagicMock()
    runner.memory_manager = MagicMock() if has_memory else None
    runner.llm = MagicMock()
    runner.tool_registry = MagicMock()
    registry.get.return_value = runner
    return registry, runner


def test_register_proactive_jobs_skips_agents_without_memory(
    tmp_path: Path,
) -> None:
    """Memory-less agent → no job built / registered."""
    from ark_agentic.plugins.jobs.proactive_setup import register_proactive_jobs

    registry, _ = _make_registry_with_agent("insurance", has_memory=False)
    manager = MagicMock()

    register_proactive_jobs(
        registry, manager, notifications_base_dir=tmp_path,
    )

    manager.register.assert_not_called()


def test_register_proactive_jobs_registers_insurance_with_memory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Memory-enabled insurance agent → InsuranceProactiveJob registered."""
    from ark_agentic.plugins.jobs import proactive_setup

    registry, runner = _make_registry_with_agent("insurance", has_memory=True)
    manager = MagicMock()

    fake_job = MagicMock()
    fake_job_cls = MagicMock(return_value=fake_job)
    monkeypatch.setattr(
        "ark_agentic.agents.insurance.proactive_job.InsuranceProactiveJob",
        fake_job_cls,
    )

    register_proactive_jobs = proactive_setup.register_proactive_jobs
    register_proactive_jobs(
        registry, manager, notifications_base_dir=tmp_path,
    )

    fake_job_cls.assert_called_once()
    manager.register.assert_called_once_with(fake_job)


def test_register_proactive_jobs_skips_unregistered_agents(
    tmp_path: Path,
) -> None:
    """Agents not in the registry are silently skipped (no KeyError)."""
    from ark_agentic.plugins.jobs.proactive_setup import register_proactive_jobs

    registry = MagicMock()
    registry.list_ids.return_value = []  # nothing registered
    manager = MagicMock()

    register_proactive_jobs(
        registry, manager, notifications_base_dir=tmp_path,
    )

    manager.register.assert_not_called()
