"""Tests for ``CachedMemoryRepository`` — caching + invalidation."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from ark_agentic.core.db.engine import (
    init_schema,
    reset_engine_for_testing,
    set_engine_for_testing,
)
from ark_agentic.core.storage.cache_adapter import (
    get_cache,
    reset_cache_for_testing,
)
from ark_agentic.core.storage.decorators.memory import CachedMemoryRepository
from ark_agentic.core.storage.factory import build_memory_repository
from ark_agentic.core.storage.repository.file.memory import FileMemoryRepository
from ark_agentic.core.storage.repository.sqlite.memory import (
    SqliteMemoryRepository,
)


@pytest.fixture(autouse=True)
def _reset_state():
    reset_cache_for_testing()
    reset_engine_for_testing()
    yield
    reset_cache_for_testing()
    reset_engine_for_testing()


@pytest.fixture
async def file_inner(tmp_path: Path) -> FileMemoryRepository:
    return FileMemoryRepository(tmp_path / "memory")


@pytest.fixture
async def sqlite_inner() -> SqliteMemoryRepository:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
    )
    set_engine_for_testing(engine)
    await init_schema()
    return SqliteMemoryRepository(engine)


# ── Read-through caching ──────────────────────────────────────────


async def test_read_caches_subsequent_reads(file_inner):
    cache = get_cache()
    repo = CachedMemoryRepository(file_inner, cache)
    await repo.upsert_headings("u1", "## Profile\nname: A\n")

    first = await repo.read("u1")
    assert "Profile" in first

    # Replace inner with a stub that raises if touched — second read must
    # come from the cache.
    class _Boom:
        async def read(self, *a, **kw):
            raise AssertionError("inner.read should not be called on cache hit")

    repo._inner = _Boom()  # type: ignore[assignment]
    second = await repo.read("u1")
    assert second == first


async def test_read_miss_populates_cache(sqlite_inner):
    cache = get_cache()
    repo = CachedMemoryRepository(sqlite_inner, cache)
    await repo.upsert_headings("u1", "## Profile\nx\n")

    assert await cache.get("mem:u1") is None

    await repo.read("u1")

    cached = await cache.get("mem:u1")
    assert cached is not None and "Profile" in cached


async def test_read_caches_empty_string(file_inner):
    """Empty 'no memory' state is itself cacheable; otherwise cold users
    re-read the (missing) file on every chat turn."""
    cache = get_cache()
    repo = CachedMemoryRepository(file_inner, cache)

    content = await repo.read("u-cold")
    assert content == ""
    # Empty string IS cached (it's a real value, not a None miss).
    assert await cache.get("mem:u-cold") == ""


# ── Invalidation ──────────────────────────────────────────────────


async def test_upsert_headings_invalidates_cache(sqlite_inner):
    cache = get_cache()
    repo = CachedMemoryRepository(sqlite_inner, cache)
    await repo.upsert_headings("u1", "## A\n1\n")
    await repo.read("u1")  # populate cache

    await repo.upsert_headings("u1", "## B\n2\n")

    assert await cache.get("mem:u1") is None


async def test_overwrite_invalidates_cache(file_inner):
    cache = get_cache()
    repo = CachedMemoryRepository(file_inner, cache)
    await repo.upsert_headings("u1", "## A\n1\n")
    await repo.read("u1")

    await repo.overwrite("u1", "fresh\n")

    assert await cache.get("mem:u1") is None


# ── Pass-through ──────────────────────────────────────────────────


async def test_list_users_passes_through(file_inner):
    repo = CachedMemoryRepository(file_inner, get_cache())
    await repo.upsert_headings("u1", "## A\n1\n")
    await repo.upsert_headings("u2", "## B\n2\n")

    users = await repo.list_users()
    assert set(users) == {"u1", "u2"}


# ── Factory wiring ────────────────────────────────────────────────


def test_factory_wraps_by_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("DB_TYPE", raising=False)
    repo = build_memory_repository(workspace_dir=tmp_path)
    assert isinstance(repo, CachedMemoryRepository)
    assert isinstance(repo.inner, FileMemoryRepository)


def test_factory_opt_out_returns_raw_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv("DB_TYPE", raising=False)
    repo = build_memory_repository(workspace_dir=tmp_path, cached=False)
    assert isinstance(repo, FileMemoryRepository)
