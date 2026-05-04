"""Storage factory dispatch tests — env-driven backend selection.

The factories no longer accept ``engine=`` parameters; the active engine
comes from each domain's ``engine.py`` accessor. Tests inject a process-
wide engine via ``set_engine_for_testing``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from ark_agentic.core.db.engine import (
    init_schema,
    reset_engine_for_testing,
    set_engine_for_testing,
)
from ark_agentic.core.storage.repository.file.agent_state import (
    FileAgentStateRepository,
)
from ark_agentic.core.storage.repository.file.memory import FileMemoryRepository
from ark_agentic.core.storage.repository.file.session import FileSessionRepository
from ark_agentic.core.storage.repository.sqlite.agent_state import (
    SqliteAgentStateRepository,
)
from ark_agentic.core.storage.repository.sqlite.memory import (
    SqliteMemoryRepository,
)
from ark_agentic.core.storage.repository.sqlite.session import (
    SqliteSessionRepository,
)
from ark_agentic.core.storage.factory import (
    build_agent_state_repository,
    build_memory_repository,
    build_session_repository,
)
from ark_agentic.services.notifications.factory import (
    build_notification_repository,
)
from ark_agentic.services.notifications.storage.file import (
    FileNotificationRepository,
)
from ark_agentic.services.notifications.storage.sqlite import (
    SqliteNotificationRepository,
)


@pytest.fixture(autouse=True)
def _clean_engine_cache():
    reset_engine_for_testing()
    yield
    reset_engine_for_testing()


@pytest.fixture
async def sqlite_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
    )
    set_engine_for_testing(engine)
    await init_schema()
    return engine


def test_build_session_returns_file_when_db_type_unset(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
):
    monkeypatch.delenv("DB_TYPE", raising=False)

    repo = build_session_repository(sessions_dir=tmp_path, cached=False)

    assert isinstance(repo, FileSessionRepository)


async def test_build_session_returns_sqlite_when_db_type_sqlite(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, sqlite_engine,
):
    monkeypatch.setenv("DB_TYPE", "sqlite")

    repo = build_session_repository(sessions_dir=tmp_path, cached=False)

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

    repo = build_memory_repository(workspace_dir=tmp_path)

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

    repo = build_agent_state_repository(workspace_dir=tmp_path)

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

    repo = build_notification_repository(base_dir=tmp_path)

    assert isinstance(repo, SqliteNotificationRepository)


def test_unknown_db_type_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("DB_TYPE", "redis")

    with pytest.raises(ValueError, match="Unsupported DB_TYPE"):
        build_session_repository(sessions_dir=tmp_path, cached=False)


def test_file_without_dir_raises(monkeypatch: pytest.MonkeyPatch):
    """File backend must complain when its required directory is omitted,
    instead of silently constructing a repository rooted at None."""
    monkeypatch.delenv("DB_TYPE", raising=False)

    with pytest.raises(ValueError, match="sessions_dir"):
        build_session_repository(sessions_dir=None, cached=False)


async def test_sqlite_session_does_not_need_dir(
    monkeypatch: pytest.MonkeyPatch, sqlite_engine,
):
    """SQLite path must not require sessions_dir (a file-backend concern)."""
    monkeypatch.setenv("DB_TYPE", "sqlite")

    repo = build_session_repository(cached=False)

    assert isinstance(repo, SqliteSessionRepository)
