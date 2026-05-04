"""Integration: env-driven backend switching wires SessionManager correctly.

After the engine encapsulation refactor, the public signature is engine-free:
tests inject the per-test engine via ``set_engine_for_testing`` and the
factory + SessionManager pick it up automatically.
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
from ark_agentic.core.session import SessionManager
from ark_agentic.core.storage.repository.file.session import FileSessionRepository
from ark_agentic.core.storage.repository.sqlite.session import (
    SqliteSessionRepository,
)


@pytest.fixture(autouse=True)
def _clean_engine_cache():
    reset_engine_for_testing()
    yield
    reset_engine_for_testing()


async def _setup_sqlite_engine(connection_str: str):
    engine = create_async_engine(
        connection_str,
        future=True,
        connect_args={"check_same_thread": False},
    )
    set_engine_for_testing(engine)
    await init_schema()
    return engine


def _unwrap(repo):
    """Look through CachedSessionRepository wrapper to the raw backend."""
    inner = getattr(repo, "inner", None)
    return inner if inner is not None else repo


def test_session_manager_uses_file_backend_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv("DB_TYPE", raising=False)

    sm = SessionManager(tmp_path)

    assert isinstance(_unwrap(sm._repository), FileSessionRepository)


async def test_session_manager_uses_sqlite_when_db_type_sqlite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("DB_TYPE", "sqlite")
    await _setup_sqlite_engine("sqlite+aiosqlite:///:memory:")

    sm = SessionManager(tmp_path)

    assert isinstance(_unwrap(sm._repository), SqliteSessionRepository)


async def test_session_manager_e2e_under_sqlite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    """End-to-end: create_session → add_message → reload must work under
    SQLite with foreign-key enforcement on."""
    from datetime import datetime

    from ark_agentic.core.types import AgentMessage, MessageRole

    monkeypatch.setenv("DB_TYPE", "sqlite")
    db_path = tmp_path / "ark.db"
    await _setup_sqlite_engine(f"sqlite+aiosqlite:///{db_path}")

    sm = SessionManager(tmp_path / "sessions")
    s = await sm.create_session(user_id="u1", model="m", provider="p")
    await sm.add_message(
        s.session_id, "u1",
        AgentMessage(
            role=MessageRole.USER, content="hi", timestamp=datetime.now(),
        ),
    )

    # Fresh manager → exercises load path through the repository.
    sm2 = SessionManager(tmp_path / "sessions")
    loaded = await sm2.load_session(s.session_id, "u1")
    assert loaded is not None
    assert [m.content for m in loaded.messages] == ["hi"]

    deleted = await sm2.delete_session(s.session_id, "u1")
    assert deleted is True
    assert await sm2.load_session(s.session_id, "u1") is None


async def test_session_manager_admin_list_all_users_under_sqlite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    """``list_sessions_from_disk(user_id=None)`` must return cross-user
    sessions under SQLite via the new ``list_all_sessions`` protocol method."""
    monkeypatch.setenv("DB_TYPE", "sqlite")
    db_path = tmp_path / "ark.db"
    await _setup_sqlite_engine(f"sqlite+aiosqlite:///{db_path}")

    sm = SessionManager(tmp_path / "sessions")
    await sm.create_session(user_id="alice")
    await sm.create_session(user_id="bob")

    sm2 = SessionManager(tmp_path / "sessions")
    sessions = await sm2.list_sessions_from_disk(user_id=None)

    user_ids = {s.user_id for s in sessions}
    assert user_ids == {"alice", "bob"}
