"""One-shot migration: file backend → SQLite.

Idempotent — re-runs skip rows whose primary key already exists. Reuses the
SQLite Repository implementations so we don't duplicate write logic.

Usage::

    python -m ark_agentic.scripts.migrate_file_to_sqlite \
        --sessions-dir data/sessions \
        --memory-dir data/ark_memory \
        --notifications-dir data/notifications \
        --db-url sqlite+aiosqlite:///data/ark.db \
        [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from ..core.db.config import DBConfig
from ..core.db.engine import get_async_engine, init_schema
from ..core.db.models import (
    AgentState,
    NotificationRow,
    SessionMeta,
    UserMemory,
)
from ..core.persistence import SessionStore, TranscriptManager
from ..core.storage.backends.sqlite.agent_state import SqliteAgentStateRepository
from ..core.storage.backends.sqlite.memory import SqliteMemoryRepository
from ..core.storage.backends.sqlite.notification import SqliteNotificationRepository
from ..core.storage.backends.sqlite.session import SqliteSessionRepository
from ..services.notifications.store import NotificationStore

logger = logging.getLogger(__name__)


@dataclass
class MigrationStats:
    sessions: int = 0
    session_messages: int = 0
    memory_users: int = 0
    agent_state_keys: int = 0
    notifications: int = 0
    skipped: dict[str, int] = field(default_factory=dict)

    def bump_skip(self, kind: str) -> None:
        self.skipped[kind] = self.skipped.get(kind, 0) + 1


# ── Sessions ──────────────────────────────────────────────────────


async def _migrate_sessions(
    engine: AsyncEngine,
    sessions_dir: Path,
    stats: MigrationStats,
    *,
    dry_run: bool,
) -> None:
    if not sessions_dir.exists():
        return

    repo = SqliteSessionRepository(engine)
    transcript = TranscriptManager(sessions_dir)
    store = SessionStore(sessions_dir)

    # Iterate per user dir.
    for user_dir in sessions_dir.iterdir():
        if not user_dir.is_dir():
            continue
        user_id = user_dir.name
        store_entries = store.load(user_id, skip_cache=True)
        for sid, entry in store_entries.items():
            async with engine.connect() as conn:
                exists = (await conn.execute(
                    select(SessionMeta.__table__.c.session_id).where(
                        SessionMeta.__table__.c.session_id == sid,
                    )
                )).first()
            if exists:
                stats.bump_skip("session_meta")
                continue

            if dry_run:
                stats.sessions += 1
                continue

            await repo.create(
                sid, user_id,
                model=entry.model,
                provider=entry.provider,
                state=entry.state,
            )
            await repo.update_meta(sid, user_id, entry)
            stats.sessions += 1

            for msg in transcript.load_messages(sid, user_id):
                await repo.append_message(sid, user_id, msg)
                stats.session_messages += 1


# ── User memory (MEMORY.md) ───────────────────────────────────────


async def _migrate_memory(
    engine: AsyncEngine,
    memory_dir: Path,
    stats: MigrationStats,
    *,
    dry_run: bool,
) -> None:
    if not memory_dir.exists():
        return

    repo = SqliteMemoryRepository(engine)
    for user_dir in memory_dir.iterdir():
        if not user_dir.is_dir():
            continue
        memory_file = user_dir / "MEMORY.md"
        if not memory_file.exists():
            continue
        user_id = user_dir.name

        async with engine.connect() as conn:
            exists = (await conn.execute(
                select(UserMemory.__table__.c.user_id).where(
                    UserMemory.__table__.c.user_id == user_id,
                )
            )).first()
        if exists:
            stats.bump_skip("user_memory")
            continue

        if dry_run:
            stats.memory_users += 1
            continue

        content = memory_file.read_text(encoding="utf-8")
        await repo.overwrite(user_id, content)
        stats.memory_users += 1


# ── Agent state markers (.last_*) ──────────────────────────────────


async def _migrate_agent_state(
    engine: AsyncEngine,
    workspace_dir: Path,
    stats: MigrationStats,
    *,
    dry_run: bool,
) -> None:
    if not workspace_dir.exists():
        return

    repo = SqliteAgentStateRepository(engine)
    for user_dir in workspace_dir.iterdir():
        if not user_dir.is_dir():
            continue
        user_id = user_dir.name
        for marker in user_dir.iterdir():
            if not marker.is_file() or not marker.name.startswith("."):
                continue
            key = marker.name[1:]  # strip leading dot
            # Skip non-state files like ``.last_dream.bak`` (ext != value)
            # — convention: treat any leading-dot file as a state marker.
            value = marker.read_text(encoding="utf-8").strip()

            async with engine.connect() as conn:
                existing = (await conn.execute(
                    select(AgentState.__table__.c.user_id).where(
                        AgentState.__table__.c.user_id == user_id,
                        AgentState.__table__.c.key == key,
                    )
                )).first()
            if existing:
                stats.bump_skip("agent_state")
                continue

            if dry_run:
                stats.agent_state_keys += 1
                continue

            await repo.set(user_id, key, value)
            stats.agent_state_keys += 1


# ── Notifications ─────────────────────────────────────────────────


async def _migrate_notifications(
    engine: AsyncEngine,
    notifications_dir: Path,
    stats: MigrationStats,
    *,
    dry_run: bool,
) -> None:
    if not notifications_dir.exists():
        return

    repo = SqliteNotificationRepository(engine)
    file_store = NotificationStore(base_dir=notifications_dir)

    for user_dir in notifications_dir.iterdir():
        if not user_dir.is_dir():
            continue
        user_id = user_dir.name
        listing = await file_store.list_recent(user_id, limit=10_000)
        for n in listing.notifications:
            async with engine.connect() as conn:
                exists = (await conn.execute(
                    select(NotificationRow.__table__.c.notification_id).where(
                        NotificationRow.__table__.c.notification_id == n.notification_id,
                    )
                )).first()
            if exists:
                stats.bump_skip("notification")
                continue

            if dry_run:
                stats.notifications += 1
                continue

            await repo.save(n)
            if n.read:
                await repo.mark_read(user_id, [n.notification_id])
            stats.notifications += 1


# ── Driver ────────────────────────────────────────────────────────


async def migrate(
    *,
    sessions_dir: Path | None,
    memory_dir: Path | None,
    notifications_dir: Path | None,
    db_url: str,
    dry_run: bool,
) -> MigrationStats:
    cfg = DBConfig(db_type="sqlite", connection_str=db_url)
    engine = get_async_engine(cfg)
    await init_schema(engine)

    stats = MigrationStats()

    if sessions_dir is not None:
        await _migrate_sessions(engine, sessions_dir, stats, dry_run=dry_run)

    if memory_dir is not None:
        await _migrate_memory(engine, memory_dir, stats, dry_run=dry_run)
        # Agent state markers live alongside MEMORY.md (workspace_dir).
        await _migrate_agent_state(engine, memory_dir, stats, dry_run=dry_run)

    if notifications_dir is not None:
        await _migrate_notifications(
            engine, notifications_dir, stats, dry_run=dry_run,
        )

    return stats


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="migrate_file_to_sqlite",
        description="Idempotent migration from file backend to SQLite.",
    )
    p.add_argument("--sessions-dir", type=Path, default=None)
    p.add_argument("--memory-dir", type=Path, default=None)
    p.add_argument("--notifications-dir", type=Path, default=None)
    p.add_argument(
        "--db-url",
        default="sqlite+aiosqlite:///data/ark.db",
        help="Target DB connection string (default: sqlite+aiosqlite:///data/ark.db)",
    )
    p.add_argument("--dry-run", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = _build_parser().parse_args(argv)
    stats = asyncio.run(
        migrate(
            sessions_dir=args.sessions_dir,
            memory_dir=args.memory_dir,
            notifications_dir=args.notifications_dir,
            db_url=args.db_url,
            dry_run=args.dry_run,
        )
    )
    print(json.dumps({
        "sessions": stats.sessions,
        "session_messages": stats.session_messages,
        "memory_users": stats.memory_users,
        "agent_state_keys": stats.agent_state_keys,
        "notifications": stats.notifications,
        "skipped": stats.skipped,
        "dry_run": args.dry_run,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
