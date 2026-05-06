"""Tests for the alembic migration helper.

Builds a tiny on-disk alembic env in ``tmp_path`` so the helper is exercised
end-to-end (env.py → versions/ → upgrade head) without depending on any
real plugin's migration directory.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table, inspect
from sqlalchemy.ext.asyncio import create_async_engine

from ark_agentic.core.storage.database.migrate import (
    init_for_testing,
    upgrade_to_head,
)


_ENV_PY = dedent(
    """
    from alembic import context

    config = context.config
    connection = config.attributes.get("connection")
    target_metadata = config.attributes.get("target_metadata")
    version_table = config.attributes.get("version_table", "alembic_version")

    if connection is None:
        raise RuntimeError("env.py expects a live connection in attributes")

    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        version_table=version_table,
    )
    with context.begin_transaction():
        context.run_migrations()
    """
).lstrip()


_REVISION_INITIAL = dedent(
    '''
    """initial widgets

    Revision ID: 0001initial
    Revises:
    Create Date: 2026-05-05 00:00:00
    """
    from alembic import op
    import sqlalchemy as sa


    revision = "0001initial"
    down_revision = None
    branch_labels = None
    depends_on = None


    def upgrade():
        op.create_table(
            "widgets",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("name", sa.String(64)),
        )


    def downgrade():
        op.drop_table("widgets")
    '''
).lstrip()


def _build_alembic_env(root: Path) -> Path:
    migrations_dir = root / "migrations"
    versions_dir = migrations_dir / "versions"
    versions_dir.mkdir(parents=True)
    (migrations_dir / "env.py").write_text(_ENV_PY, encoding="utf-8")
    (versions_dir / "0001_initial.py").write_text(
        _REVISION_INITIAL, encoding="utf-8",
    )
    return migrations_dir


def _build_metadata() -> MetaData:
    md = MetaData()
    Table(
        "widgets", md,
        Column("id", Integer, primary_key=True),
        Column("name", String(64)),
    )
    return md


async def test_init_for_testing_creates_managed_tables(
    tmp_path: Path,
) -> None:
    md = _build_metadata()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    await init_for_testing(md, engine)

    async with engine.connect() as conn:
        names = await conn.run_sync(
            lambda c: set(inspect(c).get_table_names())
        )
    assert "widgets" in names
    # Fast path does not insert an alembic version table.
    assert not any(n.startswith("alembic_version") for n in names)


async def test_upgrade_to_head_creates_tables_and_version_row(
    tmp_path: Path,
) -> None:
    migrations_dir = _build_alembic_env(tmp_path)
    md = _build_metadata()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    await upgrade_to_head(
        metadata=md,
        migrations_dir=migrations_dir,
        engine=engine,
        version_table="alembic_version_test",
    )

    async with engine.connect() as conn:
        names = await conn.run_sync(
            lambda c: set(inspect(c).get_table_names())
        )
        rev = await conn.exec_driver_sql(
            "SELECT version_num FROM alembic_version_test"
        )
        version = rev.scalar_one()

    assert "widgets" in names
    assert "alembic_version_test" in names
    assert version == "0001initial"


async def test_upgrade_to_head_is_idempotent(tmp_path: Path) -> None:
    migrations_dir = _build_alembic_env(tmp_path)
    md = _build_metadata()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    await upgrade_to_head(
        metadata=md, migrations_dir=migrations_dir,
        engine=engine, version_table="alembic_version_test",
    )
    # Second run should not raise and should not duplicate the version row.
    await upgrade_to_head(
        metadata=md, migrations_dir=migrations_dir,
        engine=engine, version_table="alembic_version_test",
    )

    async with engine.connect() as conn:
        rev = await conn.exec_driver_sql(
            "SELECT COUNT(*) FROM alembic_version_test"
        )
        count = rev.scalar_one()
    assert count == 1


async def test_upgrade_to_head_stamps_legacy_create_all_deployment(
    tmp_path: Path,
) -> None:
    """Legacy: ``create_all`` already produced the managed tables but no
    ``alembic_version_*``. First ``upgrade_to_head`` must stamp head, not
    re-execute the initial revision (which would fail on the existing
    table)."""
    migrations_dir = _build_alembic_env(tmp_path)
    md = _build_metadata()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    # Simulate the legacy state: tables exist via metadata.create_all,
    # no alembic_version table yet.
    await init_for_testing(md, engine)

    await upgrade_to_head(
        metadata=md, migrations_dir=migrations_dir,
        engine=engine, version_table="alembic_version_test",
    )

    async with engine.connect() as conn:
        rev = await conn.exec_driver_sql(
            "SELECT version_num FROM alembic_version_test"
        )
        version = rev.scalar_one()
    # Head was stamped without running upgrade.
    assert version == "0001initial"


async def test_upgrade_to_head_independent_version_tables(
    tmp_path: Path,
) -> None:
    """Two distinct version tables let two features coexist in one DB."""
    migrations_dir = _build_alembic_env(tmp_path)
    md = _build_metadata()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    await upgrade_to_head(
        metadata=md, migrations_dir=migrations_dir,
        engine=engine, version_table="alembic_version_a",
    )
    # Same migrations dir, different version_table — should be tracked
    # independently and not clash with an existing widgets table.
    # (Re-running the same revision against the same metadata via a different
    # version table goes through the stamp path because widgets exists.)
    await upgrade_to_head(
        metadata=md, migrations_dir=migrations_dir,
        engine=engine, version_table="alembic_version_b",
    )

    async with engine.connect() as conn:
        names = await conn.run_sync(
            lambda c: set(inspect(c).get_table_names())
        )
    assert {"alembic_version_a", "alembic_version_b"}.issubset(names)


@pytest.fixture(autouse=True)
def _suppress_alembic_logger_propagation(caplog: pytest.LogCaptureFixture):
    """Alembic's ``alembic.runtime.migration`` logger is INFO-level chatty;
    the helper tests don't assert on its output."""
    yield
