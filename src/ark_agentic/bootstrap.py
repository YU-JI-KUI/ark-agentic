"""Storage bootstrap — initialises every domain's schema.

Lives at package root, not under ``core/``: ``core`` must not import any
``services/*`` or ``studio/*`` (one-way dependency). Bootstrap is
**composition-root code** — it orchestrates schema init across all known
domains, which inherently means importing them.

Each domain owns its ``init_schema()`` against its own
``DeclarativeBase.metadata``. ``AsyncEngine`` is fully encapsulated by
per-domain ``engine.py`` modules — never returned or plumbed through.

CLI scaffolds and tests can call this directly without spinning up the
FastAPI app.
"""

from __future__ import annotations


async def bootstrap_storage() -> None:
    """Trigger schema initialisation for every storage domain.

    - ``DB_TYPE=file`` → no-op for core / jobs / notifications; studio
      still initialises against its dedicated SQLite file.
    - ``DB_TYPE=sqlite`` → create core / jobs / notifications / studio tables.
    """
    from .core.db.config import load_db_config_from_env
    from .core.db.engine import init_schema as init_core_schema
    from .services.jobs.engine import init_schema as init_jobs_schema
    from .services.notifications.engine import init_schema as init_notif_schema
    from .studio.services.auth.engine import init_schema as init_studio_schema

    cfg = load_db_config_from_env()
    if cfg.db_type == "sqlite":
        await init_core_schema()
        await init_jobs_schema()
        await init_notif_schema()
    # Studio initialises regardless: file mode uses its dedicated engine.
    await init_studio_schema()
