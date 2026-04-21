"""验证 services/jobs/bindings.py 的解耦行为。

测试不需要 apscheduler 也能跑(BaseJob mock 即可)。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from ark_agentic.services.jobs import (
    apply_proactive_job_bindings,
    build_proactive_job_bindings,
)
from ark_agentic.services.jobs.base import JobMeta


@dataclass
class _FakeRunner:
    """最小 runner stub,仅用于 setattr/getattr。"""
    pass


def _make_fake_job(job_id: str = "test_job") -> Any:
    job = MagicMock()
    job.meta = JobMeta(job_id=job_id, cron="0 9 * * *")
    return job


def test_build_with_none_returns_empty_bindings() -> None:
    bindings = build_proactive_job_bindings(job=None)
    assert bindings.job is None


def test_apply_no_op_when_job_is_none() -> None:
    runner = _FakeRunner()
    bindings = build_proactive_job_bindings(job=None)
    result = apply_proactive_job_bindings(runner, bindings)
    assert result is runner
    assert not hasattr(runner, "_warmup_tasks")


def test_apply_appends_warmup_task() -> None:
    runner = _FakeRunner()
    job = _make_fake_job()
    bindings = build_proactive_job_bindings(job=job)
    apply_proactive_job_bindings(runner, bindings)

    tasks = getattr(runner, "_warmup_tasks", None)
    assert tasks is not None
    assert len(tasks) == 1
    assert callable(tasks[0])


def test_apply_appends_to_existing_tasks() -> None:
    runner = _FakeRunner()
    existing_task = AsyncMock()
    setattr(runner, "_warmup_tasks", [existing_task])

    job = _make_fake_job()
    apply_proactive_job_bindings(runner, build_proactive_job_bindings(job=job))

    tasks = getattr(runner, "_warmup_tasks")
    assert len(tasks) == 2
    assert tasks[0] is existing_task


@pytest.mark.asyncio
async def test_warmup_task_skips_when_manager_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """get_job_manager() 返回 None 时(未启用 ENABLE_JOB_MANAGER),应静默跳过。"""
    runner = _FakeRunner()
    job = _make_fake_job()
    apply_proactive_job_bindings(runner, build_proactive_job_bindings(job=job))

    # 跳过 manager 模块的实际 import,直接 mock get_job_manager 返回 None
    import ark_agentic.services.jobs.manager as manager_mod
    monkeypatch.setattr(manager_mod, "get_job_manager", lambda: None)

    task = runner._warmup_tasks[0]  # type: ignore[attr-defined]
    await task()  # 不应抛异常
    assert job.method_calls == []  # 未调用 register


@pytest.mark.asyncio
async def test_warmup_task_registers_when_manager_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """get_job_manager() 返回实例时,应调用 register(job)。"""
    runner = _FakeRunner()
    job = _make_fake_job(job_id="reg_test")
    apply_proactive_job_bindings(runner, build_proactive_job_bindings(job=job))

    fake_manager = MagicMock()
    import ark_agentic.services.jobs.manager as manager_mod
    monkeypatch.setattr(manager_mod, "get_job_manager", lambda: fake_manager)

    task = runner._warmup_tasks[0]  # type: ignore[attr-defined]
    await task()
    fake_manager.register.assert_called_once_with(job)


@pytest.mark.asyncio
async def test_runner_warmup_executes_warmup_tasks() -> None:
    """验证 AgentRunner.warmup() 真的会执行 _warmup_tasks 列表。"""
    from ark_agentic.core.runner import AgentRunner

    # 不构造完整 runner(避免依赖 LLM/SessionManager),直接 mock
    runner = MagicMock(spec=AgentRunner)
    runner._warmup_tasks = [AsyncMock(), AsyncMock()]
    runner.warmup = AgentRunner.warmup.__get__(runner)

    await runner.warmup()
    for task in runner._warmup_tasks:
        task.assert_awaited_once()


@pytest.mark.asyncio
async def test_runner_warmup_no_tasks_attribute() -> None:
    """没有 _warmup_tasks 属性时 warmup() 应该 no-op。"""
    from ark_agentic.core.runner import AgentRunner

    runner = MagicMock(spec=AgentRunner)
    if hasattr(runner, "_warmup_tasks"):
        del runner._warmup_tasks
    runner.warmup = AgentRunner.warmup.__get__(runner)

    await runner.warmup()  # 不应抛
