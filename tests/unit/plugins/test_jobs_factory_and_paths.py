"""``services/jobs`` factory + paths sanity tests.

Mirrors ``test_notifications_paths`` shape — confirms the path env override
and the factory's DB_TYPE dispatch.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ark_agentic.plugins.jobs.factory import build_job_run_repository
from ark_agentic.plugins.jobs.paths import get_job_runs_base_dir
from ark_agentic.plugins.jobs.storage.file import FileJobRunRepository
from ark_agentic.plugins.jobs.storage.sqlite import SqliteJobRunRepository


def test_default_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JOB_RUNS_DIR", raising=False)
    assert get_job_runs_base_dir() == Path("data/ark_job_runs")


def test_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    custom = tmp_path / "custom_job_runs"
    monkeypatch.setenv("JOB_RUNS_DIR", str(custom))
    assert get_job_runs_base_dir() == custom


def test_factory_returns_file_backend_by_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.delenv("DB_TYPE", raising=False)
    repo = build_job_run_repository(base_dir=tmp_path)
    assert isinstance(repo, FileJobRunRepository)


def test_factory_returns_sqlite_backend_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ark_agentic.core.storage.database.config import DBConfig
    from ark_agentic.core.storage.database.engine import (
        get_async_engine,
        reset_engine_cache,
        set_engine_for_testing,
    )

    reset_engine_cache()
    monkeypatch.setenv("DB_TYPE", "sqlite")
    cfg = DBConfig(connection_str="sqlite+aiosqlite:///:memory:")
    set_engine_for_testing(get_async_engine(cfg))
    try:
        repo = build_job_run_repository()
        assert isinstance(repo, SqliteJobRunRepository)
    finally:
        reset_engine_cache()


def test_factory_rejects_file_mode_without_base_dir(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DB_TYPE", "file")
    with pytest.raises(ValueError, match="base_dir"):
        build_job_run_repository()


def test_reexported_from_package() -> None:
    from ark_agentic.plugins.jobs import (
        JobRunRepository,
        build_job_run_repository as reexported_factory,
        get_job_runs_base_dir as reexported_path,
    )

    assert reexported_factory is build_job_run_repository
    assert reexported_path is get_job_runs_base_dir
    assert JobRunRepository is not None
