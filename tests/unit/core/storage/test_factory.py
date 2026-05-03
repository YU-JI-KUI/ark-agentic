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
from ark_agentic.core.storage.backends.file.agent_state import (
    FileAgentStateRepository,
)
from ark_agentic.core.storage.backends.file.memory import FileMemoryRepository
from ark_agentic.core.storage.backends.file.memory_cache import MemoryCache
from ark_agentic.core.storage.backends.file.notification import (
    FileNotificationRepository,
)
from ark_agentic.core.storage.backends.file.session import FileSessionRepository
from ark_agentic.core.storage.backends.sqlite.agent_state import (
    SqliteAgentStateRepository,
)
from ark_agentic.core.storage.backends.sqlite.memory import (
    SqliteMemoryRepository,
)
from ark_agentic.core.storage.backends.sqlite.notification import (
    SqliteNotificationRepository,
)
from ark_agentic.core.storage.backends.sqlite.session import (
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


def test_sqlite_without_engine_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
):
    monkeypatch.setenv("DB_TYPE", "sqlite")

    with pytest.raises(RuntimeError, match="engine"):
        build_session_repository(sessions_dir=tmp_path, engine=None)
