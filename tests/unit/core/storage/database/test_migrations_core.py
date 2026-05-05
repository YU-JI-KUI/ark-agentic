"""Hand-written initial migration must produce the same schema as the
ORM models — anything caught here is a divergence between the migration
file and ``Base.metadata``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import inspect
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from ark_agentic.core.storage.database.base import Base
from ark_agentic.core.storage.database.migrate import (
    init_for_testing,
    upgrade_to_head,
)

# Importing the models module registers tables on Base.metadata.
from ark_agentic.core.storage.database import models  # noqa: F401


import ark_agentic.core.storage.database as _db_pkg

_CORE_MIGRATIONS = Path(_db_pkg.__file__).parent / "migrations"


def _dump_schema(connection: Connection) -> dict:
    """Return ``{table: {columns: ..., indexes: ...}}`` for diffing."""
    inspector = inspect(connection)
    out: dict = {}
    for table in inspector.get_table_names():
        cols = {}
        pk_cols = set(
            inspector.get_pk_constraint(table)["constrained_columns"]
        )
        for col in inspector.get_columns(table):
            cols[col["name"]] = (
                str(col["type"]),
                bool(col["nullable"]),
                col["name"] in pk_cols,
            )
        idx = {}
        for i in inspector.get_indexes(table):
            idx[i["name"]] = (tuple(i["column_names"]), bool(i.get("unique")))
        out[table] = {"columns": cols, "indexes": idx}
    return out


async def test_alembic_schema_matches_metadata_create_all(
    tmp_path: pytest.TempPathFactory,
) -> None:
    """A: ``upgrade_to_head`` from the hand-written migration.
    B: ``metadata.create_all`` from the ORM models.
    Schemas must be byte-equivalent (ignoring the alembic version table)."""
    engine_alembic = create_async_engine("sqlite+aiosqlite:///:memory:")
    await upgrade_to_head(
        metadata=Base.metadata,
        migrations_dir=_CORE_MIGRATIONS,
        engine=engine_alembic,
        version_table="alembic_version_core",
    )

    engine_orm = create_async_engine("sqlite+aiosqlite:///:memory:")
    await init_for_testing(Base.metadata, engine_orm)

    async with engine_alembic.connect() as conn:
        schema_a = await conn.run_sync(_dump_schema)
    async with engine_orm.connect() as conn:
        schema_b = await conn.run_sync(_dump_schema)

    # Strip the alembic bookkeeping table from path A.
    schema_a.pop("alembic_version_core", None)

    assert set(schema_a) == set(schema_b), (
        f"table sets differ: alembic={set(schema_a)} vs orm={set(schema_b)}"
    )
    for table in schema_a:
        assert schema_a[table]["columns"] == schema_b[table]["columns"], (
            f"column drift on {table!r}: "
            f"alembic={schema_a[table]['columns']} "
            f"orm={schema_b[table]['columns']}"
        )
        assert schema_a[table]["indexes"] == schema_b[table]["indexes"], (
            f"index drift on {table!r}: "
            f"alembic={schema_a[table]['indexes']} "
            f"orm={schema_b[table]['indexes']}"
        )


async def test_alembic_creates_version_table_with_isolated_name() -> None:
    """Core uses ``alembic_version_core`` so plugins (which use their own
    ``alembic_version_<plugin>``) cannot collide on version history."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    await upgrade_to_head(
        metadata=Base.metadata,
        migrations_dir=_CORE_MIGRATIONS,
        engine=engine,
        version_table="alembic_version_core",
    )

    async with engine.connect() as conn:
        names = await conn.run_sync(
            lambda c: set(inspect(c).get_table_names())
        )
    assert "alembic_version_core" in names
    assert "alembic_version" not in names  # default name must NOT be used
