"""Integration test for the file → SQLite migration script."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from ark_agentic.core.storage.database.config import DBConfig
from ark_agentic.core.storage.database.engine import (
    get_async_engine,
    reset_engine_cache,
)
from ark_agentic.core.storage.file.memory import FileMemoryRepository
from ark_agentic.core.storage.file.session import FileSessionRepository
from ark_agentic.core.storage.database.sqlite.memory import (
    SqliteMemoryRepository,
)
from ark_agentic.core.storage.database.sqlite.session import (
    SqliteSessionRepository,
)
from ark_agentic.core.types import AgentMessage, MessageRole
from scripts.migrations.file_to_sqlite import migrate
from ark_agentic.plugins.jobs.storage.sqlite import SqliteJobRunRepository
from ark_agentic.plugins.notifications.models import Notification
from ark_agentic.plugins.notifications.storage.file import (
    FileNotificationRepository,
)
from ark_agentic.plugins.notifications.storage.sqlite import (
    SqliteNotificationRepository,
)


@pytest.fixture(autouse=True)
def _clean_engine_cache():
    reset_engine_cache()
    yield
    reset_engine_cache()


async def _seed_file_data(tmp_path: Path) -> tuple[Path, Path, Path]:
    sessions_dir = tmp_path / "sessions"
    memory_dir = tmp_path / "memory"
    notifications_dir = tmp_path / "notifications"
    sessions_dir.mkdir()
    memory_dir.mkdir()
    notifications_dir.mkdir()

    # Session
    session_repo = FileSessionRepository(sessions_dir)
    await session_repo.create("s1", "u1", model="m", provider="p", state={"k": "v"})
    await session_repo.append_message(
        "s1", "u1",
        AgentMessage(role=MessageRole.USER, content="hello", timestamp=datetime.now()),
    )

    # Memory + last_dream marker (now persisted on user_memory.last_dream_at)
    memory_repo = FileMemoryRepository(memory_dir)
    await memory_repo.upsert_headings("u1", "## Profile\nname: A\n")
    await memory_repo.set_last_dream_at("u1", 1700000000.0)

    # Job-run marker — pre-refactor layout: dotfile next to MEMORY.md
    (memory_dir / "u1" / ".last_job_test_job").write_text(
        "1700000111.0", encoding="utf-8",
    )

    # Notification
    notif_repo = FileNotificationRepository(notifications_dir)
    await notif_repo.save(Notification(
        notification_id="n1", user_id="u1", job_id="job_x",
        title="t", body="b",
    ))

    return sessions_dir, memory_dir, notifications_dir


async def test_migrate_copies_all_entities(tmp_path: Path):
    sessions_dir, memory_dir, notifications_dir = await _seed_file_data(tmp_path)

    stats = await migrate(
        agent_id="agent_a",
        sessions_dir=sessions_dir,
        memory_dir=memory_dir,
        notifications_dir=notifications_dir,
        db_url="sqlite+aiosqlite:///:memory:",
        dry_run=False,
    )

    assert stats.sessions == 1
    assert stats.session_messages == 1
    assert stats.memory_users == 1
    assert stats.last_dream_markers == 1
    assert stats.job_runs == 1
    assert stats.notifications == 1


async def test_migrate_round_trips_data_into_sqlite_repos(tmp_path: Path):
    sessions_dir, memory_dir, notifications_dir = await _seed_file_data(tmp_path)

    db_path = tmp_path / "ark.db"
    db_url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
    await migrate(
        agent_id="agent_a",
        sessions_dir=sessions_dir,
        memory_dir=memory_dir,
        notifications_dir=notifications_dir,
        db_url=db_url,
        dry_run=False,
    )

    # Open the same engine and verify each Repository sees the migrated data.
    # The migrate() call already created every domain's schema; we just
    # need a working engine reference here to construct read repos.
    cfg = DBConfig(connection_str=db_url)
    engine = get_async_engine(cfg)

    session_repo = SqliteSessionRepository(engine, agent_id="agent_a")
    msgs = await session_repo.load_messages("s1", "u1")
    assert [m.content for m in msgs] == ["hello"]

    memory_repo = SqliteMemoryRepository(engine, agent_id="agent_a")
    assert "Profile" in await memory_repo.read("u1")
    assert await memory_repo.get_last_dream_at("u1") == 1700000000.0

    job_run_repo = SqliteJobRunRepository(engine)
    assert await job_run_repo.get_last_run("u1", "test_job") == 1700000111.0

    notif_repo = SqliteNotificationRepository(engine)
    listing = await notif_repo.list_recent("u1")
    assert [n.notification_id for n in listing.notifications] == ["n1"]


async def test_migrate_is_idempotent(tmp_path: Path):
    sessions_dir, memory_dir, notifications_dir = await _seed_file_data(tmp_path)

    db_path = tmp_path / "ark.db"
    db_url = f"sqlite+aiosqlite:///{db_path.as_posix()}"

    first = await migrate(
        agent_id="agent_a",
        sessions_dir=sessions_dir,
        memory_dir=memory_dir,
        notifications_dir=notifications_dir,
        db_url=db_url,
        dry_run=False,
    )
    assert first.sessions == 1

    reset_engine_cache()
    second = await migrate(
        agent_id="agent_a",
        sessions_dir=sessions_dir,
        memory_dir=memory_dir,
        notifications_dir=notifications_dir,
        db_url=db_url,
        dry_run=False,
    )
    # Second pass writes nothing new — every PK already present.
    assert second.sessions == 0
    assert second.skipped.get("session_meta") == 1
    assert second.skipped.get("user_memory") == 1
    assert second.skipped.get("job_run") == 1
    assert second.skipped.get("notification") == 1


async def test_migrate_dry_run_does_not_write(tmp_path: Path):
    sessions_dir, memory_dir, notifications_dir = await _seed_file_data(tmp_path)

    db_path = tmp_path / "ark.db"
    db_url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
    stats = await migrate(
        agent_id="agent_a",
        sessions_dir=sessions_dir,
        memory_dir=memory_dir,
        notifications_dir=notifications_dir,
        db_url=db_url,
        dry_run=True,
    )

    # Counts reflect what *would* be migrated, but the DB is untouched.
    # ``migrate(dry_run=True)`` still ran init_schema, so the tables
    # exist; they're just empty.
    assert stats.sessions >= 1
    cfg = DBConfig(connection_str=db_url)
    engine = get_async_engine(cfg)
    session_repo = SqliteSessionRepository(engine, agent_id="agent_a")
    assert await session_repo.list_session_ids("u1") == []
