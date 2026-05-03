"""Storage factory dispatch tests — env-driven backend selection."""

from __future__ import annotations

from pathlib import Path

import pytest

from ark_agentic.core.db.config import DBConfig
from ark_agentic.core.db.engine import (
    get_async_engine,
    init_schema,
    reset_engine_cache,
)
from ark_agentic.core.storage.repository.file.agent_state import (
    FileAgentStateRepository,
)
from ark_agentic.core.storage.repository.file.memory import FileMemoryRepository
from ark_agentic.core.storage.inproc_cache import MemoryCache
from ark_agentic.core.storage.repository.file.notification import (
    FileNotificationRepository,
)
from ark_agentic.core.storage.repository.file.session import FileSessionRepository
from ark_agentic.core.storage.repository.sqlite.agent_state import (
    SqliteAgentStateRepository,
)
from ark_agentic.core.storage.repository.sqlite.memory import (
    SqliteMemoryRepository,
)
from ark_agentic.core.storage.repository.sqlite.notification import (
    SqliteNotificationRepository,
)
from ark_agentic.core.storage.repository.sqlite.session import (
    SqliteSessionRepository,
)
from ark_agentic.core.storage.factory import (
    build_agent_state_repository,
    build_cache,
    build_memory_repository,
    build_notification_repository,
    build_session_repository,
)


@pytest.fixture(autouse=True)
def _clean_engine_cache():
    reset_engine_cache()
    yield
    reset_engine_cache()


@pytest.fixture
async def sqlite_engine():
    cfg = DBConfig(
        db_type="sqlite", connection_str="sqlite+aiosqlite:///:memory:",
    )
    engine = get_async_engine(cfg)
    await init_schema(engine)
    return engine


def test_build_session_returns_file_when_db_type_unset(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
):
    monkeypatch.delenv("DB_TYPE", raising=False)

    repo = build_session_repository(sessions_dir=tmp_path)

    assert isinstance(repo, FileSessionRepository)


async def test_build_session_returns_sqlite_when_db_type_sqlite(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, sqlite_engine,
):
    monkeypatch.setenv("DB_TYPE", "sqlite")

    repo = build_session_repository(sessions_dir=tmp_path, engine=sqlite_engine)

    assert isinstance(repo, SqliteSessionRepository)


async def test_build_memory_returns_file_when_unset(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
):
    monkeypatch.delenv("DB_TYPE", raising=False)

    repo = build_memory_repository(workspace_dir=tmp_path)

    assert isinstance(repo, FileMemoryRepository)


async def test_build_memory_returns_sqlite_when_sqlite(
    monkeypatch: pytest.MonkeyPatch, sqlite_engine, tmp_path: Path,
):
    monkeypatch.setenv("DB_TYPE", "sqlite")

    repo = build_memory_repository(workspace_dir=tmp_path, engine=sqlite_engine)

    assert isinstance(repo, SqliteMemoryRepository)


async def test_build_agent_state_returns_file_when_unset(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
):
    monkeypatch.delenv("DB_TYPE", raising=False)

    repo = build_agent_state_repository(workspace_dir=tmp_path)

    assert isinstance(repo, FileAgentStateRepository)


async def test_build_agent_state_returns_sqlite_when_sqlite(
    monkeypatch: pytest.MonkeyPatch, sqlite_engine, tmp_path: Path,
):
    monkeypatch.setenv("DB_TYPE", "sqlite")

    repo = build_agent_state_repository(
        workspace_dir=tmp_path, engine=sqlite_engine,
    )

    assert isinstance(repo, SqliteAgentStateRepository)


async def test_build_notification_returns_file_when_unset(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
):
    monkeypatch.delenv("DB_TYPE", raising=False)

    repo = build_notification_repository(base_dir=tmp_path)

    assert isinstance(repo, FileNotificationRepository)


async def test_build_notification_returns_sqlite_when_sqlite(
    monkeypatch: pytest.MonkeyPatch, sqlite_engine, tmp_path: Path,
):
    monkeypatch.setenv("DB_TYPE", "sqlite")

    repo = build_notification_repository(
        base_dir=tmp_path, engine=sqlite_engine,
    )

    assert isinstance(repo, SqliteNotificationRepository)


def test_build_cache_returns_memory_cache(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("DB_TYPE", raising=False)

    cache = build_cache()

    assert isinstance(cache, MemoryCache)


def test_unknown_db_type_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("DB_TYPE", "redis")

    with pytest.raises(ValueError, match="Unsupported DB_TYPE"):
        build_session_repository(sessions_dir=tmp_path)


async def test_sqlite_without_engine_falls_back_to_global(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
):
    """When engine=None in sqlite mode the factory falls back to get_async_engine()
    instead of raising, making call-sites that have no engine reference self-sufficient."""
    monkeypatch.setenv("DB_TYPE", "sqlite")
    monkeypatch.setenv("DB_CONNECTION_STR", f"sqlite+aiosqlite:///{tmp_path}/fallback.db")

    from ark_agentic.core.db.engine import get_async_engine, init_schema
    engine = get_async_engine()
    await init_schema(engine)

    repo = build_session_repository(sessions_dir=tmp_path, engine=None)

    from ark_agentic.core.storage.repository.sqlite.session import SqliteSessionRepository
    assert isinstance(repo, SqliteSessionRepository)


def test_file_without_dir_raises(monkeypatch: pytest.MonkeyPatch):
    """File backend must complain when its required directory is omitted,
    instead of silently constructing a repository rooted at None."""
    monkeypatch.delenv("DB_TYPE", raising=False)

    with pytest.raises(ValueError, match="sessions_dir"):
        build_session_repository(sessions_dir=None)


async def test_sqlite_session_does_not_need_dir(
    monkeypatch: pytest.MonkeyPatch, sqlite_engine,
):
    """SQLite path must not require sessions_dir (a file-backend concern)."""
    monkeypatch.setenv("DB_TYPE", "sqlite")

    repo = build_session_repository(engine=sqlite_engine)

    assert isinstance(repo, SqliteSessionRepository)
