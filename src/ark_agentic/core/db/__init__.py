"""Core database engine + ORM models.

Owns the shared AsyncEngine accessor and the core ``Base`` for sessions /
user memory tables. Each independent feature has its own ``DeclarativeBase``
and its own ``init_schema()`` — this Base only covers core tables.

PR3 will swap ``init_schema`` for Alembic when PG migration enters scope.
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
