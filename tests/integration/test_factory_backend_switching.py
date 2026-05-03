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
