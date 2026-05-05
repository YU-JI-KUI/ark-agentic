"""One-shot migration: file backend → SQLite.

Idempotent — re-runs skip rows whose primary key already exists. Reads
through ``FileXxxRepository`` (the same code production runs against) and
writes through ``SqliteXxxRepository`` so the migration speaks only the
storage Protocols.

Run::

    uv run python scripts/migrations/file_to_sqlite.py \\
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

from ark_agentic.core.storage.database.config import DBConfig
from ark_agentic.core.storage.database.engine import (
    get_async_engine,
    init_schema as init_core_schema,
    set_engine_for_testing,
)
from ark_agentic.core.storage.database.models import (
    SessionMeta,
    UserMemory,
)
from ark_agentic.core.storage.database.sqlite.memory import (
    SqliteMemoryRepository,
)
from ark_agentic.core.storage.database.sqlite.session import (
    SqliteSessionRepository,
)
from ark_agentic.core.storage.file.memory import FileMemoryRepository
from ark_agentic.core.storage.file.session import FileSessionRepository
from ark_agentic.plugins.jobs.engine import init_schema as init_jobs_schema
from ark_agentic.plugins.jobs.storage.models import JobRunRow
from ark_agentic.plugins.jobs.storage.sqlite import SqliteJobRunRepository
from ark_agentic.plugins.notifications.engine import (
    init_schema as init_notif_schema,
)
from ark_agentic.plugins.notifications.storage.file import (
    FileNotificationRepository,
)
from ark_agentic.plugins.notifications.storage.models import NotificationRow
from ark_agentic.plugins.notifications.storage.sqlite import (
    SqliteNotificationRepository,
)
from ark_agentic.plugins.studio.services.auth.engine import (
    init_schema as init_studio_schema,
)

logger = logging.getLogger(__name__)


@dataclass
class MigrationStats:
    sessions: int = 0
    session_messages: int = 0
    memory_users: int = 0
    last_dream_markers: int = 0
    job_runs: int = 0
    notifications: int = 0
    skipped: dict[str, int] = field(default_factory=dict)

    def bump_skip(self, kind: str) -> None:
        self.skipped[kind] = self.skipped.get(kind, 0) + 1


# ── Sessions ──────────────────────────────────────────────────────


async def _migrate_sessions(
    engine: AsyncEngine,
    sessions_dir: Path,
    agent_id: str,
    stats: MigrationStats,
    *,
    dry_run: bool,
) -> None:
    if not sessions_dir.exists():
        return

    src = FileSessionRepository(sessions_dir)
    dst = SqliteSessionRepository(engine, agent_id=agent_id)

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
                        SessionMeta.agent_id == agent_id,
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
    agent_id: str,
    stats: MigrationStats,
    *,
    dry_run: bool,
) -> None:
    """Migrate MEMORY.md content + last_dream_at marker.

    The ``.last_dream`` dotfile is read through the same
    ``FileMemoryRepository`` that production now uses; the timestamp lands
    on ``user_memory.last_dream_at`` via ``SqliteMemoryRepository``.
    """
    if not memory_dir.exists():
        return

    src = FileMemoryRepository(memory_dir)
    dst = SqliteMemoryRepository(engine, agent_id=agent_id)

    for user_id in await src.list_users():
        async with engine.connect() as conn:
            exists = (await conn.execute(
                select(UserMemory.user_id).where(
                    UserMemory.agent_id == agent_id,
                    UserMemory.user_id == user_id,
                )
            )).first()

        if exists:
            stats.bump_skip("user_memory")
        elif dry_run:
            stats.memory_users += 1
        else:
            content = await src.read(user_id)
            await dst.overwrite(user_id, content)
            stats.memory_users += 1

        last_dream = await src.get_last_dream_at(user_id)
        if last_dream is None:
            continue
        if dry_run:
            stats.last_dream_markers += 1
            continue
        await dst.set_last_dream_at(user_id, last_dream)
        stats.last_dream_markers += 1


# ── Job-run markers (.last_job_<id>) ──────────────────────────────


async def _migrate_job_runs(
    engine: AsyncEngine,
    memory_dir: Path,
    stats: MigrationStats,
    *,
    dry_run: bool,
) -> None:
    """Migrate per-(user, job) last-run dotfiles into the ``job_runs`` table.

    Pre-refactor the scanner stored ``.last_job_<job_id>`` next to MEMORY.md
    inside the agent's workspace, so this function expects
    ``memory_dir`` to be that workspace (same semantics as
    ``_migrate_memory``). When migrating multiple agents, run the script
    once per agent. job_id is globally unique across agents so the target
    table needs no agent partitioning.
    """
    if not memory_dir.exists():
        return

    dst = SqliteJobRunRepository(engine)

    for user_dir in memory_dir.iterdir():
        if not user_dir.is_dir():
            continue
        user_id = user_dir.name
        for marker in user_dir.iterdir():
            if not marker.is_file():
                continue
            if not marker.name.startswith(".last_job_"):
                continue
            job_id = marker.name[len(".last_job_"):]
            try:
                last_ts = float(marker.read_text(encoding="utf-8").strip())
            except (OSError, ValueError):
                stats.bump_skip("job_run_unparseable")
                continue

            async with engine.connect() as conn:
                existing = (await conn.execute(
                    select(JobRunRow.user_id).where(
                        JobRunRow.user_id == user_id,
                        JobRunRow.job_id == job_id,
                    )
                )).first()
            if existing:
                stats.bump_skip("job_run")
                continue
            if dry_run:
                stats.job_runs += 1
                continue

            await dst.set_last_run(user_id, job_id, last_ts)
            stats.job_runs += 1


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
    agent_id: str,
    sessions_dir: Path | None,
    memory_dir: Path | None,
    notifications_dir: Path | None,
    db_url: str,
    dry_run: bool,
) -> MigrationStats:
    """Per-agent migration. The session/memory directories are the
    per-agent paths from the file backend; the SQLite target rows land
    under ``agent_id`` so future per-agent reads see them.
    """
    if not agent_id:
        raise ValueError("migrate() requires a non-empty agent_id")
    cfg = DBConfig(connection_str=db_url)
    engine = get_async_engine(cfg)
    # Each domain owns its own schema; run them all so the migration target
    # has every required table regardless of which adapters this run uses.
    set_engine_for_testing(engine)
    await init_core_schema(engine)
    await init_jobs_schema()
    await init_notif_schema()
    await init_studio_schema()

    stats = MigrationStats()

    if sessions_dir is not None:
        await _migrate_sessions(
            engine, sessions_dir, agent_id, stats, dry_run=dry_run,
        )

    if memory_dir is not None:
        await _migrate_memory(
            engine, memory_dir, agent_id, stats, dry_run=dry_run,
        )
        # Per-(user, job) last-run dotfiles still live under the legacy
        # memory_dir layout (``{agent}/{user}/.last_job_<id>``). They are
        # routed into the jobs feature's own table here. New file-mode
        # writes go to ``data/ark_job_runs/``.
        await _migrate_job_runs(engine, memory_dir, stats, dry_run=dry_run)

    if notifications_dir is not None:
        await _migrate_notifications(
            engine, notifications_dir, stats, dry_run=dry_run,
        )

    return stats


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="file_to_sqlite",
        description="Idempotent migration from file backend to SQLite.",
    )
    p.add_argument(
        "--agent-id",
        required=True,
        help="Bind every migrated session/memory row to this agent_id.",
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
            agent_id=args.agent_id,
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
        "last_dream_markers": stats.last_dream_markers,
        "job_runs": stats.job_runs,
        "notifications": stats.notifications,
        "skipped": stats.skipped,
        "dry_run": args.dry_run,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
