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
    # No decorator wrapping any more: the in-memory mirror lives on the
    # MemoryManager itself, the repo is the raw file backend.
    assert isinstance(mgr._repo, FileMemoryRepository)
    assert mgr.config.workspace_dir == str(tmp_path)


async def test_memory_manager_round_trip_through_real_file_repo(tmp_path: Path) -> None:
    """End-to-end: build_memory_manager → write → read returns the same content."""
    mgr = build_memory_manager(tmp_path)

    await mgr.write_memory("u1", "## Profile\nname: Alice\n")
    content = await mgr.read_memory("u1")

    assert "Profile" in content
    assert "Alice" in content


# ── In-memory mirror (parallels SessionManager._sessions) ─────────


async def test_read_memory_caches_in_memory(tmp_path: Path) -> None:
    """Second read for the same user hits the in-memory mirror, not the repo."""
    mgr = build_memory_manager(tmp_path)
    await mgr.write_memory("u1", "## A\n1\n")

    first = await mgr.read_memory("u1")
    assert "A" in first

    # Replace the repo with a stub that raises if read is called.
    class _Boom:
        async def read(self, *a, **kw):
            raise AssertionError("read should be served from in-memory mirror")
    mgr._repo = _Boom()  # type: ignore[assignment]

    second = await mgr.read_memory("u1")
    assert second == first


async def test_read_memory_caches_empty_string_for_cold_user(tmp_path: Path) -> None:
    """Cold users (no MEMORY.md) cache the empty string so subsequent reads
    don't re-hit the file system every chat turn."""
    mgr = build_memory_manager(tmp_path)

    first = await mgr.read_memory("u-cold")
    assert first == ""

    class _Boom:
        async def read(self, *a, **kw):
            raise AssertionError("empty string must be cached")
    mgr._repo = _Boom()  # type: ignore[assignment]

    assert await mgr.read_memory("u-cold") == ""


async def test_write_memory_invalidates_in_memory_mirror(tmp_path: Path) -> None:
    mgr = build_memory_manager(tmp_path)
    await mgr.write_memory("u1", "## A\n1\n")
    await mgr.read_memory("u1")  # populate mirror

    await mgr.write_memory("u1", "## B\n2\n")

    # Mirror invalidated; next read computes the merged content from disk.
    content = await mgr.read_memory("u1")
    assert "A" in content and "B" in content


async def test_overwrite_eagerly_populates_mirror(tmp_path: Path) -> None:
    """overwrite() knows the exact new content; mirror is set directly,
    no extra disk read on the next read_memory call."""
    mgr = build_memory_manager(tmp_path)
    await mgr.read_memory("u1")  # cold read populates with ""

    await mgr.overwrite("u1", "fresh\n")

    class _Boom:
        async def read(self, *a, **kw):
            raise AssertionError("overwrite should populate the mirror")
    mgr._repo = _Boom()  # type: ignore[assignment]

    assert await mgr.read_memory("u1") == "fresh\n"


def test_evict_user_drops_mirror(tmp_path: Path) -> None:
    mgr = build_memory_manager(tmp_path)
    mgr._memory["u1"] = "cached"

    mgr.evict_user("u1")

    assert "u1" not in mgr._memory


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


# ---------------------------------------------------------------------------
# Dreaming control: enable_dream config + maybe_consolidate behaviour
# ---------------------------------------------------------------------------


async def test_maybe_consolidate_is_noop_when_dreaming_disabled(
    tmp_path: Path,
) -> None:
    """Default config has enable_dream=False; manager must not construct a
    dreamer and maybe_consolidate is a silent no-op."""
    mgr = build_memory_manager(tmp_path)

    assert mgr._dreamer is None
    await mgr.maybe_consolidate("anyone")  # must not raise


def test_enable_dream_requires_session_manager_and_llm_factory(
    tmp_path: Path,
) -> None:
    """Memory subsystem is the SSOT for dreamer wiring — building it without
    the inputs it needs must fail loudly, not silently disable dreaming."""
    with pytest.raises(ValueError, match="enable_dream"):
        build_memory_manager(tmp_path, enable_dream=True)


async def test_maybe_consolidate_delegates_to_internal_dreamer(
    tmp_path: Path,
) -> None:
    """When enabled, maybe_consolidate forwards to the internal dreamer's
    maybe_run; the dreamer itself stays internal to the memory subsystem."""
    from unittest.mock import MagicMock

    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    from ark_agentic.core.session import SessionManager
    from ark_agentic.core.storage.repository.file.session import (
        FileSessionRepository,
    )

    session_manager = SessionManager(
        sessions_dir=sessions_dir,
        repository=FileSessionRepository(sessions_dir),
    )
    mgr = build_memory_manager(
        tmp_path / "ws",
        enable_dream=True,
        session_manager=session_manager,
        llm_factory=lambda: MagicMock(),
    )

    assert mgr._dreamer is not None
    mgr._dreamer.maybe_run = AsyncMock()  # type: ignore[method-assign]

    await mgr.maybe_consolidate("u1")

    mgr._dreamer.maybe_run.assert_called_once_with("u1")
