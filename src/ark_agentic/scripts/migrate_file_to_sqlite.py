"""One-shot migration: file backend → SQLite.

Idempotent — re-runs skip rows whose primary key already exists. Reads
through ``FileXxxRepository`` (the same code production runs against) and
writes through ``SqliteXxxRepository`` so the migration speaks only the
storage Protocols.

Usage::

    python -m ark_agentic.scripts.migrate_file_to_sqlite \\
        --sessions-dir data/sessions \\
        --memory-dir data/ark_memory \\
        --notifications-dir data/notifications \\
        --db-url sqlite+aiosqlite:///data/ark.db \\
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
from ..core.db.engine import (
    get_async_engine,
    init_schema as init_core_schema,
    set_engine_for_testing,
)
from ..services.notifications.engine import (
    init_schema as init_notif_schema,
)
from ..studio.services.auth.engine import (
    init_schema as init_studio_schema,
)
from ..core.db.models import (
    AgentState,
    SessionMeta,
    UserMemory,
)
from ..core.storage.repository.file.agent_state import FileAgentStateRepository
from ..core.storage.repository.file.memory import FileMemoryRepository
from ..core.storage.repository.file.session import FileSessionRepository
from ..core.storage.repository.sqlite.agent_state import SqliteAgentStateRepository
from ..core.storage.repository.sqlite.memory import SqliteMemoryRepository
from ..core.storage.repository.sqlite.session import SqliteSessionRepository
from ..services.notifications.storage.file import FileNotificationRepository
from ..services.notifications.storage.models import NotificationRow
from ..services.notifications.storage.sqlite import SqliteNotificationRepository

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

    src = FileSessionRepository(sessions_dir)
    dst = SqliteSessionRepository(engine)

    for user_dir in sessions_dir.iterdir():
        if not user_dir.is_dir():
            continue
        user_id = user_dir.name
        metas = await src.list_session_metas(user_id)
        for entry in metas:
            sid = entry.session_id
            async with engine.connect() as conn:
                exists = (await conn.execute(
                    select(SessionMeta.session_id).where(
                        SessionMeta.session_id == sid,
                    )
                )).first()
            if exists:
                stats.bump_skip("session_meta")
                continue
            if dry_run:
                stats.sessions += 1
                continue

            await dst.create(
                sid, user_id,
                model=entry.model,
                provider=entry.provider,
                state=entry.state,
            )
            await dst.update_meta(sid, user_id, entry)
            stats.sessions += 1

            for msg in await src.load_messages(sid, user_id):
                await dst.append_message(sid, user_id, msg)
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

    src = FileMemoryRepository(memory_dir)
    dst = SqliteMemoryRepository(engine)

    for user_id in await src.list_users():
        async with engine.connect() as conn:
            exists = (await conn.execute(
                select(UserMemory.user_id).where(
                    UserMemory.user_id == user_id,
                )
            )).first()
        if exists:
            stats.bump_skip("user_memory")
            continue
        if dry_run:
            stats.memory_users += 1
            continue

        content = await src.read(user_id)
        await dst.overwrite(user_id, content)
        stats.memory_users += 1


# ── Agent state markers (.last_*) ──────────────────────────────────


# Markers we knowingly migrate. Anything else under ``{user}/.<key>`` is
# left in place — those are usually editor / VCS dotfiles, not state.
_KNOWN_AGENT_STATE_PREFIXES = ("last_dream", "last_job_")


async def _migrate_agent_state(
    engine: AsyncEngine,
    workspace_dir: Path,
    stats: MigrationStats,
    *,
    dry_run: bool,
) -> None:
    if not workspace_dir.exists():
        return

    src = FileAgentStateRepository(workspace_dir)
    dst = SqliteAgentStateRepository(engine)

    # Discover all (user, key) pairs by walking dir + filtering known
    # markers. Tries the known keys per user instead of scanning every
    # dotfile so we don't ingest editor / VCS leftovers.
    for user_dir in workspace_dir.iterdir():
        if not user_dir.is_dir():
            continue
        user_id = user_dir.name
        for marker in user_dir.iterdir():
            if not marker.is_file() or not marker.name.startswith("."):
                continue
            key = marker.name[1:]
            if not any(key.startswith(p) for p in _KNOWN_AGENT_STATE_PREFIXES):
                stats.bump_skip("agent_state_unknown_key")
                continue
            value = await src.get(user_id, key)
            if value is None:
                continue

            async with engine.connect() as conn:
                existing = (await conn.execute(
                    select(AgentState.user_id).where(
                        AgentState.user_id == user_id,
                        AgentState.key == key,
                    )
                )).first()
            if existing:
                stats.bump_skip("agent_state")
                continue
            if dry_run:
                stats.agent_state_keys += 1
                continue

            await dst.set(user_id, key, value)
            stats.agent_state_keys += 1


# ── Notifications ─────────────────────────────────────────────────


async def _migrate_notifications(
    engine: AsyncEngine,
    notifications_dir: Path,
    stats: MigrationStats,
    *,
    dry_run: bool,
) -> None:
    """Migrate notifications. Supports both layouts:

    - Per-agent: ``{notifications_dir}/{agent_id}/{user_id}/notifications.jsonl``
    - Flat:     ``{notifications_dir}/{user_id}/notifications.jsonl``

    Detection: if a top-level dir already contains ``notifications.jsonl`` it
    is a user dir (flat layout); otherwise it's an agent dir (per-agent layout).
    """
    if not notifications_dir.exists():
        return

    # Detect layout from the first dir we encounter.
    flat_layout = False
    for top in notifications_dir.iterdir():
        if top.is_dir():
            if (top / "notifications.jsonl").is_file():
                flat_layout = True
            break

    if flat_layout:
        await _migrate_notifications_for_agent(
            engine, notifications_dir, agent_id="", stats=stats, dry_run=dry_run,
        )
    else:
        for agent_dir in notifications_dir.iterdir():
            if not agent_dir.is_dir():
                continue
            await _migrate_notifications_for_agent(
                engine, agent_dir, agent_id=agent_dir.name,
                stats=stats, dry_run=dry_run,
            )


async def _migrate_notifications_for_agent(
    engine: AsyncEngine,
    agent_dir: Path,
    *,
    agent_id: str,
    stats: MigrationStats,
    dry_run: bool,
) -> None:
    src = FileNotificationRepository(agent_dir)
    dst = SqliteNotificationRepository(engine, agent_id=agent_id)

    for user_dir in agent_dir.iterdir():
        if not user_dir.is_dir():
            continue
        user_id = user_dir.name
        listing = await src.list_recent(user_id, limit=10_000)
        for n in listing.notifications:
            if not n.agent_id:
                n.agent_id = agent_id
            async with engine.connect() as conn:
                exists = (await conn.execute(
                    select(NotificationRow.notification_id).where(
                        NotificationRow.notification_id == n.notification_id,
                    )
                )).first()
            if exists:
                stats.bump_skip("notification")
                continue
            if dry_run:
                stats.notifications += 1
                continue

            await dst.save(n)
            if n.read:
                await dst.mark_read(user_id, [n.notification_id])
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
    # Each domain owns its own schema; run them all so the migration target
    # has every required table regardless of which adapters this run uses.
    set_engine_for_testing(engine)
    await init_core_schema(engine)
    await init_notif_schema()
    await init_studio_schema()

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
