"""SqliteJobRunRepository behavior tests."""

from __future__ import annotations

import pytest

from ark_agentic.core.db.config import DBConfig
from ark_agentic.core.db.engine import (
    get_async_engine,
    reset_engine_cache,
    set_engine_for_testing,
)
from ark_agentic.plugins.jobs.engine import init_schema as init_jobs_schema
from ark_agentic.plugins.jobs.protocol import JobRunRepository
from ark_agentic.plugins.jobs.storage.sqlite import SqliteJobRunRepository


@pytest.fixture(autouse=True)
def _clean_engine_cache():
    reset_engine_cache()
    yield
    reset_engine_cache()


@pytest.fixture
async def repo() -> SqliteJobRunRepository:
    cfg = DBConfig(
        db_type="sqlite", connection_str="sqlite+aiosqlite:///:memory:",
    )
    engine = get_async_engine(cfg)
    # Inject as the process engine so jobs' init_schema picks it up.
    set_engine_for_testing(engine)
    await init_jobs_schema()
    return SqliteJobRunRepository(engine)


async def test_implements_protocol(repo: SqliteJobRunRepository) -> None:
    assert isinstance(repo, JobRunRepository)


async def test_get_missing_returns_none(repo: SqliteJobRunRepository) -> None:
    assert await repo.get_last_run("nobody", "anything") is None


async def test_set_then_get_roundtrip(repo: SqliteJobRunRepository) -> None:
    await repo.set_last_run("u1", "j1", 555.5)

    assert await repo.get_last_run("u1", "j1") == 555.5


async def test_jobs_isolated_per_user(repo: SqliteJobRunRepository) -> None:
    await repo.set_last_run("alice", "j1", 100.0)
    await repo.set_last_run("bob", "j1", 200.0)

    assert await repo.get_last_run("alice", "j1") == 100.0
    assert await repo.get_last_run("bob", "j1") == 200.0


async def test_jobs_isolated_per_job_id(repo: SqliteJobRunRepository) -> None:
    await repo.set_last_run("u1", "job_a", 10.0)
    await repo.set_last_run("u1", "job_b", 20.0)

    assert await repo.get_last_run("u1", "job_a") == 10.0
    assert await repo.get_last_run("u1", "job_b") == 20.0


async def test_set_overwrites_via_on_conflict(
    repo: SqliteJobRunRepository,
) -> None:
    await repo.set_last_run("u1", "j1", 1.0)
    await repo.set_last_run("u1", "j1", 2.0)

    assert await repo.get_last_run("u1", "j1") == 2.0
