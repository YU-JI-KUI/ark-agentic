"""FileJobRunRepository behavior tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from ark_agentic.plugins.jobs.protocol import JobRunRepository
from ark_agentic.plugins.jobs.storage.file import FileJobRunRepository


@pytest.fixture
def base_dir(tmp_path: Path) -> Path:
    return tmp_path / "ark_job_runs"


@pytest.fixture
def repo(base_dir: Path) -> FileJobRunRepository:
    return FileJobRunRepository(base_dir)


async def test_implements_protocol(repo: FileJobRunRepository) -> None:
    assert isinstance(repo, JobRunRepository)


async def test_get_missing_returns_none(repo: FileJobRunRepository) -> None:
    assert await repo.get_last_run("u1", "j1") is None


async def test_set_then_get_roundtrip(
    repo: FileJobRunRepository, base_dir: Path,
) -> None:
    await repo.set_last_run("u1", "j1", 1234.5)

    assert (base_dir / "u1" / ".j1").exists()
    assert await repo.get_last_run("u1", "j1") == 1234.5


async def test_corrupt_dotfile_returns_none(
    repo: FileJobRunRepository, base_dir: Path,
) -> None:
    user_dir = base_dir / "u2"
    user_dir.mkdir(parents=True)
    (user_dir / ".broken").write_text("not-a-float", encoding="utf-8")

    assert await repo.get_last_run("u2", "broken") is None


async def test_jobs_isolated_per_user(repo: FileJobRunRepository) -> None:
    await repo.set_last_run("alice", "j1", 100.0)
    await repo.set_last_run("bob", "j1", 200.0)

    assert await repo.get_last_run("alice", "j1") == 100.0
    assert await repo.get_last_run("bob", "j1") == 200.0


async def test_jobs_isolated_per_job_id(repo: FileJobRunRepository) -> None:
    await repo.set_last_run("u1", "job_a", 10.0)
    await repo.set_last_run("u1", "job_b", 20.0)

    assert await repo.get_last_run("u1", "job_a") == 10.0
    assert await repo.get_last_run("u1", "job_b") == 20.0


async def test_set_overwrites(repo: FileJobRunRepository) -> None:
    await repo.set_last_run("u1", "j1", 1.0)
    await repo.set_last_run("u1", "j1", 2.0)

    assert await repo.get_last_run("u1", "j1") == 2.0
