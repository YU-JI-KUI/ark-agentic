"""Tests for ``CachedSessionRepository`` — caching + invalidation."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from ark_agentic.core.db.engine import (
    init_schema,
    reset_engine_for_testing,
    set_engine_for_testing,
)
from ark_agentic.core.persistence import SessionStoreEntry
from ark_agentic.core.storage.cache_adapter import (
    get_cache,
    reset_cache_for_testing,
)
from ark_agentic.core.storage.decorators.session import CachedSessionRepository
from ark_agentic.core.storage.factory import build_session_repository
from ark_agentic.core.storage.repository.file.session import FileSessionRepository
from ark_agentic.core.storage.repository.sqlite.session import (
    SqliteSessionRepository,
)
from ark_agentic.core.types import AgentMessage, MessageRole


@pytest.fixture(autouse=True)
def _reset_state():
    reset_cache_for_testing()
    reset_engine_for_testing()
    yield
    reset_cache_for_testing()
    reset_engine_for_testing()


@pytest.fixture
async def file_inner(tmp_path: Path) -> FileSessionRepository:
    return FileSessionRepository(tmp_path / "sessions")


@pytest.fixture
async def sqlite_inner() -> SqliteSessionRepository:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
    )
    set_engine_for_testing(engine)
    await init_schema()
    return SqliteSessionRepository(engine)


def _entry(session_id: str, updated_at: int = 1) -> SessionStoreEntry:
    return SessionStoreEntry(
        session_id=session_id,
        updated_at=updated_at,
        model="m",
        provider="p",
        state={"k": "v"},
    )


# ── Read-through caching ──────────────────────────────────────────


async def test_load_meta_caches_subsequent_reads(file_inner):
    cache = get_cache()
    repo = CachedSessionRepository(file_inner, cache)
    await repo.create("s1", "u1", "m", "p", {})
    await repo.update_meta("s1", "u1", _entry("s1"))

    # First read populates the cache.
    first = await repo.load_meta("s1", "u1")
    assert first is not None

    # Second read hits the cache — bypass inner by replacing it with a stub
    # that raises if touched.
    class _Boom:
        async def load_meta(self, *a, **kw):
            raise AssertionError("inner.load_meta should not be called on cache hit")

    repo._inner = _Boom()  # type: ignore[assignment]
    second = await repo.load_meta("s1", "u1")
    assert second == first


async def test_load_meta_miss_populates_cache(sqlite_inner):
    cache = get_cache()
    repo = CachedSessionRepository(sqlite_inner, cache)
    await repo.create("s1", "u1", "m", "p", {})
    await repo.update_meta("s1", "u1", _entry("s1"))

    # Cache should be empty at start
    assert await cache.get("sess_meta:u1:s1") is None

    await repo.load_meta("s1", "u1")

    cached = await cache.get("sess_meta:u1:s1")
    assert cached is not None
    assert cached.session_id == "s1"


async def test_load_meta_does_not_cache_misses(file_inner):
    cache = get_cache()
    repo = CachedSessionRepository(file_inner, cache)

    # No session created → load_meta returns None
    result = await repo.load_meta("absent", "u1")
    assert result is None

    # Cache must NOT remember the miss (otherwise a future create+meta
    # update would be invisible until TTL expiry).
    assert await cache.get("sess_meta:u1:absent") is None


# ── Invalidation ──────────────────────────────────────────────────


async def test_update_meta_invalidates_cache(sqlite_inner):
    cache = get_cache()
    repo = CachedSessionRepository(sqlite_inner, cache)
    await repo.create("s1", "u1", "m", "p", {})
    await repo.update_meta("s1", "u1", _entry("s1", updated_at=1))
    await repo.load_meta("s1", "u1")  # populate cache

    # Mutate via update_meta — the cache key for (u1, s1) must be gone.
    await repo.update_meta("s1", "u1", _entry("s1", updated_at=2))

    assert await cache.get("sess_meta:u1:s1") is None


async def test_delete_invalidates_cache(sqlite_inner):
    cache = get_cache()
    repo = CachedSessionRepository(sqlite_inner, cache)
    await repo.create("s1", "u1", "m", "p", {})
    await repo.update_meta("s1", "u1", _entry("s1"))
    await repo.load_meta("s1", "u1")

    await repo.delete("s1", "u1")

    assert await cache.get("sess_meta:u1:s1") is None


async def test_put_raw_transcript_invalidates_cache(file_inner):
    cache = get_cache()
    repo = CachedSessionRepository(file_inner, cache)
    await repo.create("s1", "u1", "m", "p", {})
    await repo.update_meta("s1", "u1", _entry("s1"))
    await repo.load_meta("s1", "u1")  # populate cache

    raw = await repo.get_raw_transcript("s1", "u1")
    assert raw is not None
    await repo.put_raw_transcript("s1", "u1", raw)

    assert await cache.get("sess_meta:u1:s1") is None


# ── Pass-through preserves semantics ──────────────────────────────


async def test_append_message_round_trips_through_wrapper(sqlite_inner):
    repo = CachedSessionRepository(sqlite_inner, get_cache())
    await repo.create("s1", "u1", "m", "p", {})

    msg = AgentMessage(role=MessageRole.USER, content="hi", timestamp=datetime.now())
    await repo.append_message("s1", "u1", msg)

    loaded = await repo.load_messages("s1", "u1")
    assert [m.content for m in loaded] == ["hi"]


# ── Factory wiring ───────────────────────────────────────────────


def test_factory_wraps_by_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("DB_TYPE", raising=False)
    repo = build_session_repository(sessions_dir=tmp_path)
    assert isinstance(repo, CachedSessionRepository)
    assert isinstance(repo.inner, FileSessionRepository)


def test_factory_opt_out_returns_raw_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv("DB_TYPE", raising=False)
    repo = build_session_repository(sessions_dir=tmp_path, cached=False)
    assert isinstance(repo, FileSessionRepository)
