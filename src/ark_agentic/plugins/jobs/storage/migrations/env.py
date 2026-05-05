"""Alembic env for the jobs feature schema (job_runs).

Programmatic mode: ``core.storage.database.migrate.upgrade_to_head`` injects
``connection`` / ``target_metadata`` / ``version_table`` into
``cfg.attributes``. CLI mode: alembic.ini's ``sqlalchemy.url`` opens a
temp connection, and ``JobsBase.metadata`` is loaded from imports for
autogenerate.
"""

from __future__ import annotations

from alembic import context

config = context.config

connection = config.attributes.get("connection")
target_metadata = config.attributes.get("target_metadata")
version_table = config.attributes.get(
    "version_table", "alembic_version_jobs",
)

if target_metadata is None:
    from ark_agentic.plugins.jobs.storage.models import JobsBase

    target_metadata = JobsBase.metadata


def _run_with_connection(conn) -> None:
    context.configure(
        connection=conn,
        target_metadata=target_metadata,
        version_table=version_table,
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
