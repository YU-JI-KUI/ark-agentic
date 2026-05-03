"""SqliteAgentStateRepository behavior tests."""

from __future__ import annotations

import asyncio

import pytest

from ark_agentic.core.db.config import DBConfig
from ark_agentic.core.db.engine import (
    get_async_engine,
    init_schema,
    reset_engine_cache,
)
from ark_agentic.core.storage.repository.sqlite.agent_state import (
    SqliteAgentStateRepository,
)
from ark_agentic.core.storage.protocols import AgentStateRepository


@pytest.fixture(autouse=True)
def _clean_engine_cache():
    reset_engine_cache()
    yield
    reset_engine_cache()


@pytest.fixture
async def repo() -> SqliteAgentStateRepository:
    cfg = DBConfig(
        db_type="sqlite", connection_str="sqlite+aiosqlite:///:memory:",
    )
    engine = get_async_engine(cfg)
    await init_schema(engine)
    return SqliteAgentStateRepository(engine)


async def test_implements_agent_state_repository_protocol(
    repo: SqliteAgentStateRepository,
):
    assert isinstance(repo, AgentStateRepository)


async def test_get_returns_none_when_missing(repo: SqliteAgentStateRepository):
    result = await repo.get("u1", "last_dream")

    assert result is None


async def test_set_then_get_round_trip(repo: SqliteAgentStateRepository):
    await repo.set("u1", "last_dream", "1234567890")

    assert await repo.get("u1", "last_dream") == "1234567890"


async def test_set_overwrites_previous_value(repo: SqliteAgentStateRepository):
    await repo.set("u1", "last_job_x", "1")
    await repo.set("u1", "last_job_x", "2")

    assert await repo.get("u1", "last_job_x") == "2"


async def test_key_with_dots_supported(repo: SqliteAgentStateRepository):
    await repo.set("u1", "last_job_send.notify", "ts")

    assert await repo.get("u1", "last_job_send.notify") == "ts"


async def test_list_users_with_key_filters_by_key(
    repo: SqliteAgentStateRepository,
):
    await repo.set("u1", "last_dream", "1")
    await repo.set("u2", "last_dream", "2")
    await repo.set("u3", "last_job_x", "3")

    users = await repo.list_users_with_key("last_dream")

    names = {u for u, _ in users}
    assert names == {"u1", "u2"}


async def test_list_users_with_key_orders_by_updated_desc(
    repo: SqliteAgentStateRepository,
):
    await repo.set("oldest", "last_dream", "1")
    await asyncio.sleep(0.01)
    await repo.set("middle", "last_dream", "2")
    await asyncio.sleep(0.01)
    await repo.set("newest", "last_dream", "3")

    users = await repo.list_users_with_key("last_dream", order_by_updated_desc=True)

    names = [u for u, _ in users]
    assert names == ["newest", "middle", "oldest"]


async def test_set_concurrent_inserts_no_integrity_error(
    repo: SqliteAgentStateRepository,
):
    """Two parallel set() calls for a brand-new (user, key) must both succeed
    via ON CONFLICT DO UPDATE — no IntegrityError."""
    await asyncio.gather(
        repo.set("u_race", "k", "v1"),
        repo.set("u_race", "k", "v2"),
    )

    final = await repo.get("u_race", "k")
    assert final in ("v1", "v2")
