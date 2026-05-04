"""MemoryManager delegation-layer unit tests.

PR2.5: ``MemoryManager`` is a thin async facade over ``MemoryRepository``.
Each public method delegates 1:1 to the repository; nothing else.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from ark_agentic.core.memory.manager import (
    MemoryConfig,
    MemoryManager,
    build_memory_manager,
)
from ark_agentic.core.storage.repository.file.memory import FileMemoryRepository


@pytest.fixture
def repo_mock() -> AsyncMock:
    repo = AsyncMock()
    repo.read = AsyncMock(return_value="")
    repo.upsert_headings = AsyncMock(return_value=([], []))
    repo.overwrite = AsyncMock(return_value=None)
    return repo


async def test_read_memory_delegates_to_repository(repo_mock: AsyncMock) -> None:
    repo_mock.read.return_value = "## H\nv\n"
    mgr = MemoryManager(repo_mock)

    result = await mgr.read_memory("u1")

    repo_mock.read.assert_awaited_once_with("u1")
    assert result == "## H\nv\n"


async def test_write_memory_delegates_to_repository(repo_mock: AsyncMock) -> None:
    repo_mock.upsert_headings.return_value = (["H"], [])
    mgr = MemoryManager(repo_mock)

    current, dropped = await mgr.write_memory("u1", "## H\nv\n")

    repo_mock.upsert_headings.assert_awaited_once_with("u1", "## H\nv\n")
    assert current == ["H"]
    assert dropped == []


async def test_overwrite_delegates_to_repository(repo_mock: AsyncMock) -> None:
    mgr = MemoryManager(repo_mock)

    await mgr.overwrite("u1", "fresh\n")

    repo_mock.overwrite.assert_awaited_once_with("u1", "fresh\n")


async def test_memory_manager_no_longer_exposes_memory_path() -> None:
    """memory_path was a file-backend leak — must be gone after PR2.5."""
    mgr = MemoryManager(AsyncMock())

    assert not hasattr(mgr, "memory_path"), \
        "memory_path leaks file-backend semantics; access via repository instead"


def test_build_memory_manager_wires_file_repository(tmp_path: Path) -> None:
    """Default factory still returns a working MemoryManager rooted at memory_dir."""
    mgr = build_memory_manager(tmp_path)

    assert isinstance(mgr, MemoryManager)
    # Internal repo is the file backend in default DB_TYPE=file mode.
    assert isinstance(mgr._repo, FileMemoryRepository)
    # MemoryConfig kept for back-compat; surface workspace_dir for callers
    # that read it (e.g. scanner / dream).
    assert mgr.config.workspace_dir == str(tmp_path)


async def test_memory_manager_round_trip_through_real_file_repo(tmp_path: Path) -> None:
    """End-to-end: build_memory_manager → write → read returns the same content."""
    mgr = build_memory_manager(tmp_path)

    await mgr.write_memory("u1", "## Profile\nname: Alice\n")
    content = await mgr.read_memory("u1")

    assert "Profile" in content
    assert "Alice" in content


def test_memory_config_keeps_workspace_dir() -> None:
    cfg = MemoryConfig(workspace_dir="/tmp/x")

    assert cfg.workspace_dir == "/tmp/x"


async def test_list_user_ids_delegates_to_repo() -> None:
    mock_repo = AsyncMock()
    mock_repo.list_users = AsyncMock(return_value=["alice", "bob"])
    mm = MemoryManager(repository=mock_repo, config=MemoryConfig(workspace_dir="/tmp"))

    result = await mm.list_user_ids()

    assert result == ["alice", "bob"]
    mock_repo.list_users.assert_called_once()


def test_build_memory_manager_no_longer_takes_engine(tmp_path: Path) -> None:
    """``engine`` kwarg removed — engine ownership is encapsulated by
    ``core.db.engine``, not plumbed through public signatures."""
    import inspect

    sig = inspect.signature(build_memory_manager)
    assert "engine" not in sig.parameters
    assert "db_engine" not in sig.parameters
