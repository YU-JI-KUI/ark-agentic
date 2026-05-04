"""Storage bootstrap — initialises every domain's schema.

Each domain (core / notifications / studio) owns its ``init_schema()``;
this module just calls them in sequence. ``AsyncEngine`` is fully owned
by per-domain ``engine.py`` modules — never returned or plumbed through.
"""

from __future__ import annotations


async def bootstrap_storage() -> None:
    """Trigger schema initialisation for every storage domain.

    - ``DB_TYPE=file`` → no-op for core; studio still initialises against
      its dedicated SQLite file.
    - ``DB_TYPE=sqlite`` → create core / notifications / studio tables.
    """
    from .db.config import load_db_config_from_env
    from .db.engine import init_schema as init_core_schema
    from ..services.notifications.engine import init_schema as init_notif_schema
    from ..studio.services.auth.engine import init_schema as init_studio_schema

    cfg = load_db_config_from_env()
    if cfg.db_type == "sqlite":
        await init_core_schema()
        await init_notif_schema()
    # Studio initialises regardless: file mode uses its dedicated engine.
    await init_studio_schema()
