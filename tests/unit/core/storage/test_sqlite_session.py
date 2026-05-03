"""SqliteSessionRepository behavior tests."""

from __future__ import annotations

from datetime import datetime

import pytest

from ark_agentic.core.db.config import DBConfig
from ark_agentic.core.db.engine import (
    get_async_engine,
    init_schema,
    reset_engine_cache,
)
from ark_agentic.core.storage.backends.sqlite.session import (
    SqliteSessionRepository,
)
from ark_agentic.core.storage.protocols import SessionRepository
from ark_agentic.core.types import AgentMessage, MessageRole


@pytest.fixture(autouse=True)
def _clean_engine_cache():
    reset_engine_cache()
    yield
    reset_engine_cache()


@pytest.fixture
async def repo() -> SqliteSessionRepository:
    cfg = DBConfig(
        db_type="sqlite", connection_str="sqlite+aiosqlite:///:memory:",
    )
    engine = get_async_engine(cfg)
    await init_schema(engine)
    return SqliteSessionRepository(engine)


def _msg(text: str, role: MessageRole = MessageRole.USER) -> AgentMessage:
    return AgentMessage(role=role, content=text, timestamp=datetime.now())


async def test_implements_session_repository_protocol(
    repo: SqliteSessionRepository,
):
    assert isinstance(repo, SessionRepository)


async def test_create_initializes_meta_row(repo: SqliteSessionRepository):
    await repo.create("s1", "u1", model="m", provider="p", state={"k": "v"})

    meta = await repo.load_meta("s1", "u1")
    assert meta is not None
    assert meta.model == "m"
    assert meta.state == {"k": "v"}


async def test_append_then_load_round_trip(repo: SqliteSessionRepository):
    await repo.create("s1", "u1", model="m", provider="p", state={})

    await repo.append_message("s1", "u1", _msg("hello"))
    await repo.append_message("s1", "u1", _msg("world", MessageRole.ASSISTANT))

    msgs = await repo.load_messages("s1", "u1")
    assert [m.content for m in msgs] == ["hello", "world"]


async def test_list_session_ids_returns_user_sessions(
    repo: SqliteSessionRepository,
):
    await repo.create("s1", "u1", model="m", provider="p", state={})
    await repo.create("s2", "u1", model="m", provider="p", state={})
    await repo.create("s3", "u2", model="m", provider="p", state={})

    sessions = await repo.list_session_ids("u1")

    assert set(sessions) == {"s1", "s2"}


async def test_get_put_raw_transcript_round_trip(repo: SqliteSessionRepository):
    await repo.create("s1", "u1", model="m", provider="p", state={})
    await repo.append_message("s1", "u1", _msg("hi"))

    raw = await repo.get_raw_transcript("s1", "u1")
    assert raw is not None
    assert "hi" in raw

    await repo.put_raw_transcript("s1", "u1", raw)
    again = await repo.get_raw_transcript("s1", "u1")
    # Round-trip must preserve message content
    assert "hi" in (again or "")


async def test_delete_clears_meta_and_messages(repo: SqliteSessionRepository):
    await repo.create("s1", "u1", model="m", provider="p", state={})
    await repo.append_message("s1", "u1", _msg("x"))

    deleted = await repo.delete("s1", "u1")

    assert deleted is True
    assert await repo.load_meta("s1", "u1") is None
    assert await repo.get_raw_transcript("s1", "u1") is None


async def test_finalize_is_noop(repo: SqliteSessionRepository):
    await repo.create("s1", "u1", model="m", provider="p", state={})

    await repo.finalize("s1", "u1")  # must not raise


async def test_append_assigns_increasing_seq(repo: SqliteSessionRepository):
    """Concurrent appends rely on the unique (session_id, seq) index."""
    await repo.create("s1", "u1", model="m", provider="p", state={})

    for i in range(5):
        await repo.append_message("s1", "u1", _msg(f"m{i}"))

    msgs = await repo.load_messages("s1", "u1")
    assert [m.content for m in msgs] == ["m0", "m1", "m2", "m3", "m4"]
