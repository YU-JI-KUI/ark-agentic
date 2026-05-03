"""Integration: env-driven backend switching wires SessionManager correctly.

PR2 scope: ``DB_TYPE=sqlite`` switches **SessionRepository** /
**AgentStateRepository** / **NotificationRepository** to SQLite.
``MemoryManager.read_memory`` / ``write_memory`` still call file IO inside
``core/memory/manager.py``; PR3 will inject ``MemoryRepository`` into
``core/tools/memory.py`` + ``core/memory/extractor.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ark_agentic.core.db.config import DBConfig
from ark_agentic.core.db.engine import (
    get_async_engine,
    init_schema,
    reset_engine_cache,
)
from ark_agentic.core.session import SessionManager
from ark_agentic.core.storage.backends.file.session import FileSessionRepository
from ark_agentic.core.storage.backends.sqlite.session import (
    SqliteSessionRepository,
)


@pytest.fixture(autouse=True)
def _clean_engine_cache():
    reset_engine_cache()
    yield
    reset_engine_cache()


def test_session_manager_uses_file_backend_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv("DB_TYPE", raising=False)

    sm = SessionManager(tmp_path)

    assert isinstance(sm.repository, FileSessionRepository)


async def test_session_manager_uses_sqlite_when_db_type_sqlite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("DB_TYPE", "sqlite")
    cfg = DBConfig(
        db_type="sqlite", connection_str="sqlite+aiosqlite:///:memory:",
    )
    engine = get_async_engine(cfg)
    await init_schema(engine)

    sm = SessionManager(tmp_path, db_engine=engine)

    assert isinstance(sm.repository, SqliteSessionRepository)


async def test_session_manager_e2e_under_sqlite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    """End-to-end: create_session → add_message → reload must work under
    SQLite with foreign-key enforcement on. Regression for the dual-storage
    bug where create_session bypassed the repository and add_message hit a
    FK violation against an empty session_meta."""
    from datetime import datetime

    from ark_agentic.core.types import AgentMessage, MessageRole

    monkeypatch.setenv("DB_TYPE", "sqlite")
    db_path = tmp_path / "ark.db"
    cfg = DBConfig(
        db_type="sqlite", connection_str=f"sqlite+aiosqlite:///{db_path}",
    )
    engine = get_async_engine(cfg)
    await init_schema(engine)

    sm = SessionManager(tmp_path / "sessions", db_engine=engine)
    s = await sm.create_session(user_id="u1", model="m", provider="p")
    await sm.add_message(
        s.session_id, "u1",
        AgentMessage(
            role=MessageRole.USER, content="hi", timestamp=datetime.now(),
        ),
    )

    # Fresh manager → exercises load path through the repository.
    sm2 = SessionManager(tmp_path / "sessions", db_engine=engine)
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
    cfg = DBConfig(
        db_type="sqlite", connection_str=f"sqlite+aiosqlite:///{db_path}",
    )
    engine = get_async_engine(cfg)
    await init_schema(engine)

    sm = SessionManager(tmp_path / "sessions", db_engine=engine)
    await sm.create_session(user_id="alice")
    await sm.create_session(user_id="bob")

    sm2 = SessionManager(tmp_path / "sessions", db_engine=engine)
    sessions = await sm2.list_sessions_from_disk(user_id=None)

    user_ids = {s.user_id for s in sessions}
    assert user_ids == {"alice", "bob"}
