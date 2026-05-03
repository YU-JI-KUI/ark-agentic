"""Storage bootstrap — resolves DBConfig, builds engine, initialises schema.

The single ``bootstrap_storage()`` coroutine replaces the inline
``load_db_config_from_env / get_async_engine / init_schema`` block that
used to live in ``app.py`` lifespan, keeping the app assembler free of
storage implementation details.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine


@dataclass
class StorageRuntime:
    """Resolved storage runtime produced by ``bootstrap_storage()``."""

    db_engine: "AsyncEngine | None"


async def bootstrap_storage() -> StorageRuntime:
    """Resolve DBConfig, build AsyncEngine if needed, and initialise schema.

    - ``DB_TYPE=file`` → returns ``StorageRuntime(db_engine=None)``, no engine.
    - ``DB_TYPE=sqlite`` → builds/reuses cached engine, runs ``init_schema``,
      returns ``StorageRuntime(db_engine=engine)``.
    """
    from .db.config import load_db_config_from_env
    from .db.engine import get_async_engine, init_schema

    cfg = load_db_config_from_env()
    if cfg.db_type == "file":
        return StorageRuntime(db_engine=None)

    engine = get_async_engine(cfg)
    await init_schema(engine)
    return StorageRuntime(db_engine=engine)
