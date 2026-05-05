"""FileMemoryRepository 行为测试。"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from ark_agentic.core.storage.file.memory import FileMemoryRepository
from ark_agentic.core.storage.protocols import MemoryRepository


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def repo(workspace: Path) -> FileMemoryRepository:
    return FileMemoryRepository(workspace)


async def test_implements_memory_repository_protocol(repo: FileMemoryRepository):
    assert isinstance(repo, MemoryRepository)


async def test_read_returns_empty_when_file_missing(repo: FileMemoryRepository):
    result = await repo.read("never-created")

    assert result == ""


async def test_upsert_creates_memory_file(repo: FileMemoryRepository, workspace: Path):
    current, dropped = await repo.upsert_headings("alice", "## Profile\nname: Alice\n")

    assert "Profile" in current
    assert dropped == []
    assert (workspace / "alice" / "MEMORY.md").exists()


async def test_upsert_merges_across_calls(repo: FileMemoryRepository):
    await repo.upsert_headings("bob", "## A\nfirst\n")

    await repo.upsert_headings("bob", "## B\nsecond\n")

    final = await repo.read("bob")
    assert "## A" in final
    assert "## B" in final


async def test_overwrite_replaces_content(
    repo: FileMemoryRepository, workspace: Path
):
    await repo.upsert_headings("carol", "## Old\nstale\n")

    await repo.overwrite("carol", "fresh content\n")

    assert await repo.read("carol") == "fresh content\n"


async def test_list_users_returns_only_users_with_memory(
    repo: FileMemoryRepository, workspace: Path
):
    await repo.upsert_headings("u1", "## H\nx\n")
    await repo.upsert_headings("u2", "## H\ny\n")
    (workspace / "u3").mkdir()  # no MEMORY.md

    users = await repo.list_users()

    assert set(users) == {"u1", "u2"}


async def test_list_users_orders_by_mtime_desc(
    repo: FileMemoryRepository, workspace: Path
):
    await repo.upsert_headings("oldest", "## H\nx\n")
    time.sleep(0.05)
    await repo.upsert_headings("middle", "## H\ny\n")
    time.sleep(0.05)
    await repo.upsert_headings("newest", "## H\nz\n")

    users = await repo.list_users(order_by_updated_desc=True)

    assert users == ["newest", "middle", "oldest"]


async def test_upsert_drops_heading_when_body_empty(
    repo: FileMemoryRepository,
):
    """Empty body for an existing heading triggers deletion (regression)."""
    await repo.upsert_headings("u1", "## A\ncontent\n## B\nother\n")

    current, dropped = await repo.upsert_headings("u1", "## A\n")

    assert "A" not in current
    assert "B" in current  # untouched headings preserved
    assert "A" in dropped


async def test_get_last_dream_at_missing_returns_none(
    repo: FileMemoryRepository,
):
    assert await repo.get_last_dream_at("nobody") is None


async def test_set_then_get_last_dream_at_roundtrip(
    repo: FileMemoryRepository, workspace: Path,
):
    ts = time.time()
    await repo.set_last_dream_at("u1", ts)

    assert (workspace / "u1" / ".last_dream").exists()
    got = await repo.get_last_dream_at("u1")
    assert got is not None
    assert abs(got - ts) < 1e-3


async def test_get_last_dream_at_corrupt_returns_none(
    repo: FileMemoryRepository, workspace: Path,
):
    user_dir = workspace / "u2"
    user_dir.mkdir(parents=True)
    (user_dir / ".last_dream").write_text("not-a-number", encoding="utf-8")

    assert await repo.get_last_dream_at("u2") is None


async def test_set_last_dream_at_overwrites(repo: FileMemoryRepository):
    await repo.set_last_dream_at("u3", 100.0)
    await repo.set_last_dream_at("u3", 200.0)

    assert await repo.get_last_dream_at("u3") == 200.0
