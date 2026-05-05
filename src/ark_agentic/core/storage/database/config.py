"""Database engine configuration — connection string + pool sizing.

Pure DB knobs; the file-vs-database mode decision lives in
``core.storage.mode``. ``load_db_config_from_env`` is only meaningful when
``mode.is_database()`` is true; the engine layer is what calls it.
"""

from __future__ import annotations

import os

from pydantic import BaseModel, Field

_DEFAULT_SQLITE_URL = "sqlite+aiosqlite:///data/ark.db"


class DBConfig(BaseModel):
    """Resolved DB connection configuration."""

    connection_str: str
    pool_size: int = Field(default=5, ge=1, le=200)


def load_db_config_from_env() -> DBConfig:
    """Read ``DB_CONNECTION_STR`` / ``DB_POOL_SIZE`` from the environment.

    Caller is responsible for checking ``mode.is_database()`` first; this
    function does not validate that a SQL backend is actually in use.
    """
    conn = os.environ.get("DB_CONNECTION_STR", "").strip() or _DEFAULT_SQLITE_URL

    pool_raw = os.environ.get("DB_POOL_SIZE", "5").strip()
    try:
        pool_size = int(pool_raw)
    except ValueError as e:
        raise ValueError(
            f"DB_POOL_SIZE must be an integer, got {pool_raw!r}"
        ) from e

    return DBConfig(connection_str=conn, pool_size=pool_size)
