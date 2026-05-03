"""Database engine + ORM models for the SQLite (and future PG) backend.

Tier 1 storage upgrade path: a single AsyncEngine + a single declarative Base
hosting all business tables. ``Base.metadata.create_all(engine)`` is invoked
at app startup; PR3 will swap this for Alembic when PG migration enters scope.
"""

from .base import Base
from .config import DBConfig, load_db_config_from_env
from .engine import get_async_engine, init_schema, reset_engine_cache

__all__ = [
    "Base",
    "DBConfig",
    "load_db_config_from_env",
    "get_async_engine",
    "init_schema",
    "reset_engine_cache",
]
