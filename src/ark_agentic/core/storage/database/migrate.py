"""Schema migration helper — programmatic alembic invocation per plugin.

Each feature owns an alembic data directory (``env.py`` + ``versions/``) and
its own ``alembic_version_<feature>`` table; this helper runs ``upgrade head``
against them with a connection borrowed from the shared engine.

Stamp-or-upgrade contract: when a deployment was previously bootstrapped via
``metadata.create_all`` (the managed tables exist but no
``alembic_version_*`` table is present), the helper stamps head on first
run so subsequent revisions apply cleanly without trying to recreate
tables.

Test fast path: ``init_for_testing`` skips alembic entirely and runs
``metadata.create_all`` so the suite stays cheap.
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData, inspect
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine


async def upgrade_to_head(
    *,
    metadata: MetaData,
    migrations_dir: Path,
    engine: AsyncEngine,
    version_table: str,
) -> None:
    """Run alembic ``upgrade head`` for ``metadata`` against ``engine``.

    Idempotent. On first run against a legacy ``create_all`` deployment,
    stamps head instead of upgrading so existing tables are not recreated.
    """
    async with engine.begin() as conn:
        await conn.run_sync(
            _stamp_or_upgrade,
            metadata,
            migrations_dir,
            version_table,
        )


async def init_for_testing(
    metadata: MetaData,
    engine: AsyncEngine,
) -> None:
    """Fast ``metadata.create_all`` for test fixtures only.

    Production startup goes through ``upgrade_to_head``; tests that don't
    want to spin up alembic boilerplate use this shortcut.
    """
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)


def _stamp_or_upgrade(
    connection: Connection,
    metadata: MetaData,
    migrations_dir: Path,
    version_table: str,
) -> None:
    inspector = inspect(connection)
    has_version_table = inspector.has_table(version_table)
    has_managed = any(
        inspector.has_table(t.name) for t in metadata.tables.values()
    )

    cfg = _build_config(connection, metadata, migrations_dir, version_table)

    if not has_version_table and has_managed:
        command.stamp(cfg, "head")
    else:
        command.upgrade(cfg, "head")


def _build_config(
    connection: Connection,
    metadata: MetaData,
    migrations_dir: Path,
    version_table: str,
) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(migrations_dir))
    cfg.attributes["connection"] = connection
    cfg.attributes["target_metadata"] = metadata
    cfg.attributes["version_table"] = version_table
    return cfg
