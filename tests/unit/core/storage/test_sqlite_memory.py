"""SqliteMemoryRepository behavior tests (blob strategy)."""

from __future__ import annotations

import asyncio

import pytest

from ark_agentic.core.db.config import DBConfig
from ark_agentic.core.db.engine import (
    get_async_engine,
    init_schema,
    reset_engine_cache,
)
from ark_agentic.core.storage.repository.sqlite.memory import (
    SqliteMemoryRepository,
)
from ark_agentic.core.storage.protocols import MemoryRepository


@pytest.fixture(autouse=True)
def _clean_engine_cache():
    reset_engine_cache()
    yield
    reset_engine_cache()


@pytest.fixture
async def repo() -> SqliteMemoryRepository:
    cfg = DBConfig(
        db_type="sqlite", connection_str="sqlite+aiosqlite:///:memory:",
    )
    engine = get_async_engine(cfg)
    await init_schema(engine)
    return SqliteMemoryRepository(engine)


async def test_implements_memory_repository_protocol(repo: SqliteMemoryRepository):
    assert isinstance(repo, MemoryRepository)


async def test_read_returns_empty_when_user_missing(repo: SqliteMemoryRepository):
    result = await repo.read("nobody")

    assert result == ""


async def test_upsert_creates_row(repo: SqliteMemoryRepository):
    current, dropped = await repo.upsert_headings("alice", "## Profile\nname: Alice\n")

    assert "Profile" in current
    assert dropped == []
    assert "Profile" in await repo.read("alice")


async def test_upsert_merges_across_calls(repo: SqliteMemoryRepository):
    await repo.upsert_headings("bob", "## A\nfirst\n")

    await repo.upsert_headings("bob", "## B\nsecond\n")

    final = await repo.read("bob")
    assert "## A" in final
    assert "## B" in final


async def test_overwrite_replaces_content(repo: SqliteMemoryRepository):
    await repo.upsert_headings("carol", "## Old\nstale\n")

    await repo.overwrite("carol", "fresh\n")

    assert await repo.read("carol") == "fresh\n"


async def test_list_users_returns_only_users_with_memory(
    repo: SqliteMemoryRepository,
):
    await repo.upsert_headings("u1", "## H\nx\n")
    await repo.upsert_headings("u2", "## H\ny\n")

    users = await repo.list_users()

    assert set(users) == {"u1", "u2"}


async def test_list_users_orders_by_updated_desc(repo: SqliteMemoryRepository):
    await repo.upsert_headings("oldest", "## H\nx\n")
    await asyncio.sleep(0.01)
    await repo.upsert_headings("middle", "## H\ny\n")
    await asyncio.sleep(0.01)
    await repo.upsert_headings("newest", "## H\nz\n")

    users = await repo.list_users(order_by_updated_desc=True)

    assert users == ["newest", "middle", "oldest"]


async def test_upsert_drops_heading_when_body_empty(repo: SqliteMemoryRepository):
    """Empty body for an existing heading triggers deletion (regression)."""
    await repo.upsert_headings("u1", "## A\ncontent\n## B\nother\n")

    current, dropped = await repo.upsert_headings("u1", "## A\n")

    assert "A" not in current
    assert "B" in current  # untouched headings preserved
    assert "A" in dropped


async def test_overwrite_concurrent_no_integrity_error(
    repo: SqliteMemoryRepository,
):
    """Two parallel overwrite calls on a brand-new user must both succeed —
    the upsert relies on ON CONFLICT DO UPDATE, not check-then-insert."""
    await asyncio.gather(
        repo.overwrite("racey", "first\n"),
        repo.overwrite("racey", "second\n"),
    )

    final = await repo.read("racey")
    # one of the two writes wins; both are valid — neither must raise
    assert final in ("first\n", "second\n")


async def test_get_last_dream_at_missing_returns_none(
    repo: SqliteMemoryRepository,
):
    assert await repo.get_last_dream_at("nobody") is None


async def test_set_then_get_last_dream_at_roundtrip(
    repo: SqliteMemoryRepository,
):
    await repo.set_last_dream_at("u1", 1234567.5)

    assert await repo.get_last_dream_at("u1") == 1234567.5


async def test_set_last_dream_at_creates_row_for_new_user(
    repo: SqliteMemoryRepository,
):
    """First set on a brand-new user must succeed; row is created with
    empty content + the timestamp set."""
    await repo.set_last_dream_at("newuser", 42.0)

    assert await repo.read("newuser") == ""
    assert await repo.get_last_dream_at("newuser") == 42.0


async def test_set_last_dream_at_overwrites(repo: SqliteMemoryRepository):
    await repo.set_last_dream_at("u2", 100.0)
    await repo.set_last_dream_at("u2", 200.0)

    assert await repo.get_last_dream_at("u2") == 200.0


async def test_overwrite_preserves_last_dream_at(
    repo: SqliteMemoryRepository,
):
    """Overwriting content must not clobber an existing last_dream_at marker."""
    await repo.set_last_dream_at("u3", 999.0)
    await repo.overwrite("u3", "## X\nbody\n")

    assert await repo.get_last_dream_at("u3") == 999.0
