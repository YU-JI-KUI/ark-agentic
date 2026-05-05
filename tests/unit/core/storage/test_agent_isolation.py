"""Agent isolation tests for the SQLite session/memory repositories.

Two repositories share one engine but bind to different ``agent_id``s.
Each must see only its own rows for SELECT, UPDATE, and DELETE — even
when querying with the *other* agent's session_id / user_id directly.
INSERTs land under the binding agent automatically (column default reads
from the contextvar set by ``agent_scoped_session``).
"""

from __future__ import annotations

from datetime import datetime

import pytest

from ark_agentic.core.storage.database.config import DBConfig
from ark_agentic.core.storage.database.engine import (
    get_async_engine,
    init_schema,
    reset_engine_cache,
)
from ark_agentic.core.storage.database.sqlite.memory import (
    SqliteMemoryRepository,
)
from ark_agentic.core.storage.database.sqlite.session import (
    SqliteSessionRepository,
)
from ark_agentic.core.storage.entries import SessionStoreEntry
from ark_agentic.core.types import AgentMessage, MessageRole


@pytest.fixture(autouse=True)
def _clean_engine_cache():
    reset_engine_cache()
    yield
    reset_engine_cache()


@pytest.fixture
async def engine():
    cfg = DBConfig(
        db_type="sqlite", connection_str="sqlite+aiosqlite:///:memory:",
    )
    e = get_async_engine(cfg)
    await init_schema(e)
    return e


def _msg(text: str, role: MessageRole = MessageRole.USER) -> AgentMessage:
    return AgentMessage(role=role, content=text, timestamp=datetime.now())


# ── Session repository ───────────────────────────────────────────────


async def test_session_load_meta_does_not_cross_agents(engine):
    repo_a = SqliteSessionRepository(engine, agent_id="agent_a")
    repo_b = SqliteSessionRepository(engine, agent_id="agent_b")
    await repo_a.create("s1", "u1", model="m", provider="p", state={})

    leaked = await repo_b.load_meta("s1", "u1")

    assert leaked is None


async def test_session_list_session_metas_isolated_per_agent(engine):
    repo_a = SqliteSessionRepository(engine, agent_id="agent_a")
    repo_b = SqliteSessionRepository(engine, agent_id="agent_b")
    await repo_a.create("s_a", "u1", model="m", provider="p", state={})
    await repo_b.create("s_b", "u1", model="m", provider="p", state={})

    metas_a = await repo_a.list_session_metas("u1")
    metas_b = await repo_b.list_session_metas("u1")

    assert {m.session_id for m in metas_a} == {"s_a"}
    assert {m.session_id for m in metas_b} == {"s_b"}


async def test_session_list_session_summaries_isolated_per_agent(engine):
    """``user_id=None`` returns every user under the bound agent only."""
    repo_a = SqliteSessionRepository(engine, agent_id="agent_a")
    repo_b = SqliteSessionRepository(engine, agent_id="agent_b")
    await repo_a.create("s_a", "u1", model="m", provider="p", state={})
    await repo_b.create("s_b", "u2", model="m", provider="p", state={})

    summaries_a = await repo_a.list_session_summaries()
    summaries_b = await repo_b.list_session_summaries()

    assert {s.session_id for s in summaries_a} == {"s_a"}
    assert {s.session_id for s in summaries_b} == {"s_b"}


async def test_session_list_all_sessions_isolated_per_agent(engine):
    repo_a = SqliteSessionRepository(engine, agent_id="agent_a")
    repo_b = SqliteSessionRepository(engine, agent_id="agent_b")
    await repo_a.create("s_a", "u1", model="m", provider="p", state={})
    await repo_b.create("s_b", "u2", model="m", provider="p", state={})

    pairs_a = await repo_a.list_all_sessions()

    assert pairs_a == [("u1", "s_a")]


async def test_session_delete_cannot_remove_other_agent_row(engine):
    repo_a = SqliteSessionRepository(engine, agent_id="agent_a")
    repo_b = SqliteSessionRepository(engine, agent_id="agent_b")
    await repo_a.create("s1", "u1", model="m", provider="p", state={})
    await repo_a.append_message("s1", "u1", _msg("hi"))

    deleted = await repo_b.delete("s1", "u1")

    assert deleted is False
    assert (await repo_a.load_meta("s1", "u1")) is not None
    assert [m.content for m in await repo_a.load_messages("s1", "u1")] == ["hi"]


async def test_session_load_messages_does_not_cross_agents(engine):
    repo_a = SqliteSessionRepository(engine, agent_id="agent_a")
    repo_b = SqliteSessionRepository(engine, agent_id="agent_b")
    await repo_a.create("s1", "u1", model="m", provider="p", state={})
    await repo_a.append_message("s1", "u1", _msg("secret_a"))

    leaked = await repo_b.load_messages("s1", "u1")

    assert leaked == []


async def test_session_get_raw_transcript_does_not_cross_agents(engine):
    repo_a = SqliteSessionRepository(engine, agent_id="agent_a")
    repo_b = SqliteSessionRepository(engine, agent_id="agent_b")
    await repo_a.create("s1", "u1", model="m", provider="p", state={})
    await repo_a.append_message("s1", "u1", _msg("secret_a"))

    leaked = await repo_b.get_raw_transcript("s1", "u1")

    assert leaked is None


async def test_session_update_meta_inserts_under_bound_agent(engine):
    """Writing through repo_b must not overwrite repo_a's row even when
    they share the same session_id."""
    repo_a = SqliteSessionRepository(engine, agent_id="agent_a")
    repo_b = SqliteSessionRepository(engine, agent_id="agent_b")
    entry_a = SessionStoreEntry(
        session_id="s1", updated_at=1, model="m", provider="p",
        state={"who": "a"},
    )
    entry_b = SessionStoreEntry(
        session_id="s1", updated_at=2, model="m", provider="p",
        state={"who": "b"},
    )
    await repo_a.update_meta("s1", "u1", entry_a)

    await repo_b.update_meta("s1", "u1", entry_b)

    # Each agent reads back its own state.
    seen_a = await repo_a.load_meta("s1", "u1")
    seen_b = await repo_b.load_meta("s1", "u1")
    assert seen_a is not None and seen_a.state == {"who": "a"}
    assert seen_b is not None and seen_b.state == {"who": "b"}


# ── Memory repository ────────────────────────────────────────────────


async def test_memory_read_does_not_cross_agents(engine):
    repo_a = SqliteMemoryRepository(engine, agent_id="agent_a")
    repo_b = SqliteMemoryRepository(engine, agent_id="agent_b")
    await repo_a.overwrite("alice", "## Profile\nname: alice in A\n")

    leaked = await repo_b.read("alice")

    assert leaked == ""


async def test_memory_overwrite_isolated_per_agent(engine):
    repo_a = SqliteMemoryRepository(engine, agent_id="agent_a")
    repo_b = SqliteMemoryRepository(engine, agent_id="agent_b")
    await repo_a.overwrite("alice", "## Profile\nfrom A\n")
    await repo_b.overwrite("alice", "## Profile\nfrom B\n")

    # Same user_id, two independent blobs.
    assert "from A" in await repo_a.read("alice")
    assert "from B" in await repo_b.read("alice")


async def test_memory_list_users_isolated_per_agent(engine):
    repo_a = SqliteMemoryRepository(engine, agent_id="agent_a")
    repo_b = SqliteMemoryRepository(engine, agent_id="agent_b")
    await repo_a.overwrite("alice", "## A\n1\n")
    await repo_b.overwrite("bob", "## A\n1\n")

    users_a = await repo_a.list_users()
    users_b = await repo_b.list_users()

    assert users_a == ["alice"]
    assert users_b == ["bob"]


async def test_memory_list_summaries_isolated_per_agent(engine):
    repo_a = SqliteMemoryRepository(engine, agent_id="agent_a")
    repo_b = SqliteMemoryRepository(engine, agent_id="agent_b")
    await repo_a.overwrite("alice", "## A\n1\n")
    await repo_b.overwrite("bob", "## A\n1\n")

    summaries_a = await repo_a.list_memory_summaries()
    summaries_b = await repo_b.list_memory_summaries()

    assert {s.user_id for s in summaries_a} == {"alice"}
    assert {s.user_id for s in summaries_b} == {"bob"}


async def test_memory_dream_marker_isolated_per_agent(engine):
    """Same user under two agents has independent ``last_dream_at`` markers."""
    repo_a = SqliteMemoryRepository(engine, agent_id="agent_a")
    repo_b = SqliteMemoryRepository(engine, agent_id="agent_b")
    await repo_a.set_last_dream_at("alice", 1700000000.0)

    assert await repo_a.get_last_dream_at("alice") == 1700000000.0
    assert await repo_b.get_last_dream_at("alice") is None


async def test_repos_reject_empty_agent_id(engine):
    with pytest.raises(ValueError):
        SqliteSessionRepository(engine, agent_id="")
    with pytest.raises(ValueError):
        SqliteMemoryRepository(engine, agent_id="")
