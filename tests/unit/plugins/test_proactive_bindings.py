"""验证 services/jobs/bindings.py 的解耦行为。

测试不需要 apscheduler 也能跑(BaseJob mock 即可)。
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from ark_agentic.plugins.jobs import (
    apply_proactive_job_bindings,
    build_proactive_job_bindings,
)
from ark_agentic.plugins.jobs.base import JobMeta


class _FakeRunner:
    """Minimal runner stub exposing the public ``add_warmup_hook`` surface."""

    def __init__(self) -> None:
        self.hooks: list = []

    def add_warmup_hook(self, hook) -> None:
        self.hooks.append(hook)


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
    assert runner.hooks == []


def test_apply_registers_warmup_hook() -> None:
    runner = _FakeRunner()
    job = _make_fake_job()
    apply_proactive_job_bindings(runner, build_proactive_job_bindings(job=job))

    assert len(runner.hooks) == 1
    assert callable(runner.hooks[0])


def test_apply_appends_to_existing_hooks() -> None:
    runner = _FakeRunner()
    existing = AsyncMock()
    runner.add_warmup_hook(existing)

    job = _make_fake_job()
    apply_proactive_job_bindings(runner, build_proactive_job_bindings(job=job))

    assert len(runner.hooks) == 2
    assert runner.hooks[0] is existing


@pytest.mark.asyncio
async def test_warmup_hook_skips_when_manager_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """get_job_manager() 返回 None 时(未启用 ENABLE_JOB_MANAGER),应静默跳过。"""
    runner = _FakeRunner()
    job = _make_fake_job()
    apply_proactive_job_bindings(runner, build_proactive_job_bindings(job=job))

    import ark_agentic.plugins.jobs.manager as manager_mod
    monkeypatch.setattr(manager_mod, "get_job_manager", lambda: None)

    await runner.hooks[0]()
    assert job.method_calls == []


@pytest.mark.asyncio
async def test_warmup_hook_registers_when_manager_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """get_job_manager() 返回实例时,应调用 register(job)。"""
    runner = _FakeRunner()
    job = _make_fake_job(job_id="reg_test")
    apply_proactive_job_bindings(runner, build_proactive_job_bindings(job=job))

    fake_manager = MagicMock()
    import ark_agentic.plugins.jobs.manager as manager_mod
    monkeypatch.setattr(manager_mod, "get_job_manager", lambda: fake_manager)

    await runner.hooks[0]()
    fake_manager.register.assert_called_once_with(job)


@pytest.mark.asyncio
async def test_runner_warmup_runs_every_hook() -> None:
    """BaseAgent.warmup() 调用所有通过 add_warmup_hook 注册的回调。"""
    from ark_agentic.core.runtime.base_agent import BaseAgent

    runner = MagicMock(spec=BaseAgent)
    runner._warmup_hooks = [AsyncMock(), AsyncMock()]
    runner.warmup = BaseAgent.warmup.__get__(runner)

    await runner.warmup()
    for hook in runner._warmup_hooks:
        hook.assert_awaited_once()


@pytest.mark.asyncio
async def test_runner_warmup_with_no_hooks_is_a_noop() -> None:
    from ark_agentic.core.runtime.base_agent import BaseAgent

    runner = MagicMock(spec=BaseAgent)
    runner._warmup_hooks = []
    runner.warmup = BaseAgent.warmup.__get__(runner)

    await runner.warmup()
