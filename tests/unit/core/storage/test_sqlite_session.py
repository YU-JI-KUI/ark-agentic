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
from ark_agentic.core.storage.repository.sqlite.session import (
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


# ── Authorisation: WHERE clause must scope by user_id ─────────────


async def test_load_meta_other_user_returns_none(
    repo: SqliteSessionRepository,
):
    """Calling load_meta with the wrong user_id must NOT leak the row."""
    await repo.create("s1", "u1", model="m", provider="p", state={"k": "v"})

    leaked = await repo.load_meta("s1", "u2")

    assert leaked is None


async def test_load_messages_other_user_returns_empty(
    repo: SqliteSessionRepository,
):
    await repo.create("s1", "u1", model="m", provider="p", state={})
    await repo.append_message("s1", "u1", _msg("secret"))

    leaked = await repo.load_messages("s1", "u2")

    assert leaked == []


async def test_get_raw_transcript_other_user_returns_none(
    repo: SqliteSessionRepository,
):
    await repo.create("s1", "u1", model="m", provider="p", state={})
    await repo.append_message("s1", "u1", _msg("secret"))

    leaked = await repo.get_raw_transcript("s1", "u2")

    assert leaked is None


async def test_delete_other_user_does_not_remove_row(
    repo: SqliteSessionRepository,
):
    """Wrong user_id reports False; the owner's row stays intact."""
    await repo.create("s1", "u1", model="m", provider="p", state={})
    await repo.append_message("s1", "u1", _msg("hi"))

    deleted = await repo.delete("s1", "u2")

    assert deleted is False
    # Owner can still see the session and its messages
    assert (await repo.load_meta("s1", "u1")) is not None
    assert [m.content for m in await repo.load_messages("s1", "u1")] == ["hi"]


async def test_put_raw_transcript_other_user_raises_and_keeps_owner(
    repo: SqliteSessionRepository,
):
    """Misrouted put_raw refuses; the owner's transcript stays intact."""
    from ark_agentic.core.session.format import RawJsonlValidationError

    await repo.create("s1", "u1", model="m", provider="p", state={})
    await repo.append_message("s1", "u1", _msg("owner-msg"))
    raw = await repo.get_raw_transcript("s1", "u1")
    assert raw is not None

    with pytest.raises(RawJsonlValidationError, match="not found for user"):
        await repo.put_raw_transcript("s1", "u2", raw)

    owner_msgs = await repo.load_messages("s1", "u1")
    assert [m.content for m in owner_msgs] == ["owner-msg"]


# ── Concurrent upsert: ON CONFLICT DO UPDATE on update_meta ──────


async def test_update_meta_concurrent_inserts_no_integrity_error(
    repo: SqliteSessionRepository,
):
    """Two parallel update_meta calls for a brand-new session must both
    succeed — the second must UPDATE, not raise IntegrityError."""
    import asyncio

    from ark_agentic.core.storage.entries import SessionStoreEntry

    e1 = SessionStoreEntry(
        session_id="s1", updated_at=1, model="m", provider="p", state={"k": 1},
    )
    e2 = SessionStoreEntry(
        session_id="s1", updated_at=2, model="m", provider="p", state={"k": 2},
    )

    await asyncio.gather(
        repo.update_meta("s1", "u1", e1),
        repo.update_meta("s1", "u1", e2),
    )

    final = await repo.load_meta("s1", "u1")
    assert final is not None
    # one of the two writes wins; both are valid outcomes — no exception
    assert final.state in ({"k": 1}, {"k": 2})
