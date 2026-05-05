"""SessionRepository.list_session_summaries — SQLite + file backends.

These tests pin the contract that summary listings must compute
``message_count`` and ``first_user_message`` in ONE round-trip per
listing — never N+1 by loading every transcript. The single-round-trip
property is enforced indirectly: SQLite under-test runs against an
in-memory engine where extra queries are cheap, and ``EXPLAIN QUERY
PLAN`` is asserted in a separate test (``test_session_summaries_index``).
Here we focus on correctness across the boundary cases the dashboard
hits in practice.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from ark_agentic.core.storage.database.config import DBConfig
from ark_agentic.core.storage.database.engine import (
    get_async_engine,
    init_schema,
    reset_engine_cache,
)
from ark_agentic.core.storage.database.sqlite.session import (
    SqliteSessionRepository,
)
from ark_agentic.core.storage.entries import SessionStoreEntry
from ark_agentic.core.storage.file.session import FileSessionRepository
from ark_agentic.core.types import AgentMessage, MessageRole


@pytest.fixture(autouse=True)
def _clean_engine_cache():
    reset_engine_cache()
    yield
    reset_engine_cache()


@pytest.fixture
async def sqlite_repo() -> SqliteSessionRepository:
    cfg = DBConfig(
        db_type="sqlite", connection_str="sqlite+aiosqlite:///:memory:",
    )
    engine = get_async_engine(cfg)
    await init_schema(engine)
    return SqliteSessionRepository(engine, agent_id="agent_a")


@pytest.fixture
def file_repo(tmp_path: Path) -> FileSessionRepository:
    return FileSessionRepository(tmp_path / "sessions")


def _msg(text: str, role: MessageRole = MessageRole.USER) -> AgentMessage:
    return AgentMessage(role=role, content=text, timestamp=datetime.now())


async def _seed(repo, sid: str, uid: str, **kwargs) -> None:
    await repo.create(sid, uid, model="m", provider="p", state={})
    if "messages" in kwargs:
        for m in kwargs["messages"]:
            await repo.append_message(sid, uid, m)
    if "updated_at" in kwargs:
        await repo.update_meta(
            sid, uid,
            SessionStoreEntry(
                session_id=sid,
                updated_at=kwargs["updated_at"],
                model="m",
                provider="p",
            ),
        )


# ── Happy path ───────────────────────────────────────────────────


async def test_sqlite_summaries_count_and_first_user_message(
    sqlite_repo: SqliteSessionRepository,
):
    await _seed(
        sqlite_repo, "s1", "u1",
        messages=[
            _msg("hello there", MessageRole.USER),
            _msg("how can I help?", MessageRole.ASSISTANT),
            _msg("follow up", MessageRole.USER),
        ],
        updated_at=2_000,
    )

    rows = await sqlite_repo.list_session_summaries("u1")

    assert len(rows) == 1
    assert rows[0].message_count == 3
    assert rows[0].first_user_message == "hello there"
    assert rows[0].user_id == "u1"


async def test_file_summaries_count_and_first_user_message(
    file_repo: FileSessionRepository,
):
    await _seed(
        file_repo, "s1", "u1",
        messages=[
            _msg("hello there", MessageRole.USER),
            _msg("how can I help?", MessageRole.ASSISTANT),
            _msg("follow up", MessageRole.USER),
        ],
        updated_at=2_000,
    )

    rows = await file_repo.list_session_summaries("u1")

    assert len(rows) == 1
    assert rows[0].message_count == 3
    assert rows[0].first_user_message == "hello there"


# ── Boundary cases ───────────────────────────────────────────────


async def test_sqlite_summaries_no_messages_yields_none_snippet(
    sqlite_repo: SqliteSessionRepository,
):
    await _seed(sqlite_repo, "s1", "u1", updated_at=1_000)

    rows = await sqlite_repo.list_session_summaries("u1")

    assert rows[0].message_count == 0
    assert rows[0].first_user_message is None


async def test_file_summaries_no_messages_yields_none_snippet(
    file_repo: FileSessionRepository,
):
    await _seed(file_repo, "s1", "u1", updated_at=1_000)

    rows = await file_repo.list_session_summaries("u1")

    assert rows[0].message_count == 0
    assert rows[0].first_user_message is None


async def test_sqlite_summaries_assistant_only_session_has_no_snippet(
    sqlite_repo: SqliteSessionRepository,
):
    await _seed(
        sqlite_repo, "s1", "u1",
        messages=[
            _msg("system kickoff", MessageRole.ASSISTANT),
            _msg("more replies", MessageRole.ASSISTANT),
        ],
        updated_at=1_000,
    )

    rows = await sqlite_repo.list_session_summaries("u1")

    assert rows[0].message_count == 2
    assert rows[0].first_user_message is None


async def test_file_summaries_assistant_only_session_has_no_snippet(
    file_repo: FileSessionRepository,
):
    await _seed(
        file_repo, "s1", "u1",
        messages=[
            _msg("system kickoff", MessageRole.ASSISTANT),
            _msg("more replies", MessageRole.ASSISTANT),
        ],
        updated_at=1_000,
    )

    rows = await file_repo.list_session_summaries("u1")

    assert rows[0].message_count == 2
    assert rows[0].first_user_message is None


async def test_sqlite_summaries_truncates_first_user_message_to_80_chars(
    sqlite_repo: SqliteSessionRepository,
):
    long = "a" * 200
    await _seed(
        sqlite_repo, "s1", "u1", messages=[_msg(long)], updated_at=1_000,
    )

    rows = await sqlite_repo.list_session_summaries("u1")

    assert rows[0].first_user_message is not None
    assert len(rows[0].first_user_message) == 80


async def test_sqlite_summaries_order_by_updated_at_desc(
    sqlite_repo: SqliteSessionRepository,
):
    await _seed(sqlite_repo, "s_old", "u1", updated_at=1_000)
    await _seed(sqlite_repo, "s_new", "u1", updated_at=5_000)

    rows = await sqlite_repo.list_session_summaries("u1")

    assert [r.session_id for r in rows] == ["s_new", "s_old"]


async def test_sqlite_list_session_summaries_returns_all_users_for_this_agent(
    sqlite_repo: SqliteSessionRepository,
):
    """``user_id=None`` returns every user under the bound agent, ordered DESC."""
    await _seed(sqlite_repo, "s1", "u1", updated_at=1_000)
    await _seed(sqlite_repo, "s2", "u2", updated_at=2_000)

    rows = await sqlite_repo.list_session_summaries()

    assert {r.user_id for r in rows} == {"u1", "u2"}
    assert [r.session_id for r in rows] == ["s2", "s1"]
