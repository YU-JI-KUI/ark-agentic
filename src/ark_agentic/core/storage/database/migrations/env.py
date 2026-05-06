"""Alembic env for core SQL schema (sessions + user memory).

Two run modes:

1. **Programmatic** (production startup, tests):
   ``core.storage.database.migrate.upgrade_to_head`` builds a Config that
   carries ``connection`` / ``target_metadata`` / ``version_table`` in
   ``cfg.attributes`` and drives the upgrade against an open async
   connection. This branch is what app code hits.

2. **CLI** (developer running ``alembic revision --autogenerate``):
   alembic.ini provides ``sqlalchemy.url`` and we open a temp connection.
   The metadata is loaded from imports so autogenerate has a target.
"""

from __future__ import annotations

from alembic import context

config = context.config

connection = config.attributes.get("connection")
target_metadata = config.attributes.get("target_metadata")
version_table = config.attributes.get(
    "version_table", "alembic_version_core",
)

if target_metadata is None:
    # CLI fallback: load core's metadata so autogenerate can diff it.
    from ark_agentic.core.storage.database.base import Base
    from ark_agentic.core.storage.database import models  # noqa: F401

    target_metadata = Base.metadata


def _run_with_connection(conn) -> None:
    context.configure(
        connection=conn,
        target_metadata=target_metadata,
        version_table=version_table,
        # SQLite ALTER limitations require ``batch_alter_table``; this
        # opt-in lets autogenerate emit the wrapper automatically when
        # comparing against a SQLite target.
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


if connection is not None:
    _run_with_connection(connection)
else:
    from sqlalchemy import engine_from_config, pool

    section = config.get_section(config.config_ini_section) or {}
    connectable = engine_from_config(
        section, prefix="sqlalchemy.", poolclass=pool.NullPool,
    )
    with connectable.connect() as conn:
        _run_with_connection(conn)
