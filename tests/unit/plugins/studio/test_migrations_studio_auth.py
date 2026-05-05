"""Hand-written initial migration for studio_auth must produce the same
schema as ``AuthBase.metadata`` — drift here is a divergence between the
migration file and the ORM model.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import inspect
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from ark_agentic.core.storage.database.migrate import (
    init_for_testing,
    upgrade_to_head,
)
from ark_agentic.plugins.studio.services.auth.storage.models import AuthBase

import ark_agentic.plugins.studio.services.auth.storage as _auth_storage_pkg

_AUTH_MIGRATIONS = Path(_auth_storage_pkg.__file__).parent / "migrations"


def _dump_schema(connection: Connection) -> dict:
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


async def test_alembic_schema_matches_metadata_create_all() -> None:
    engine_alembic = create_async_engine("sqlite+aiosqlite:///:memory:")
    await upgrade_to_head(
        metadata=AuthBase.metadata,
        migrations_dir=_AUTH_MIGRATIONS,
        engine=engine_alembic,
        version_table="alembic_version_studio_auth",
    )

    engine_orm = create_async_engine("sqlite+aiosqlite:///:memory:")
    await init_for_testing(AuthBase.metadata, engine_orm)

    async with engine_alembic.connect() as conn:
        schema_a = await conn.run_sync(_dump_schema)
    async with engine_orm.connect() as conn:
        schema_b = await conn.run_sync(_dump_schema)

    schema_a.pop("alembic_version_studio_auth", None)

    assert set(schema_a) == set(schema_b)
    for table in schema_a:
        assert schema_a[table]["columns"] == schema_b[table]["columns"]
        assert schema_a[table]["indexes"] == schema_b[table]["indexes"]
