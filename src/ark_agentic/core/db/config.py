"""Database configuration — env-driven backend selection.

Tier 0 (default): ``DB_TYPE`` unset or ``"file"`` → file backend, no DB engine.
Tier 1: ``DB_TYPE=sqlite`` + ``DB_CONNECTION_STR=sqlite+aiosqlite:///data/ark.db``
"""

from __future__ import annotations

import os
from typing import Literal

from pydantic import BaseModel, Field

DBType = Literal["file", "sqlite"]


class DBConfig(BaseModel):
    """Resolved DB configuration after env parsing."""

    db_type: DBType = "file"
    connection_str: str = ""
    pool_size: int = Field(default=5, ge=1, le=200)


_DEFAULT_SQLITE_URL = "sqlite+aiosqlite:///data/ark.db"


def load_db_config_from_env() -> DBConfig:
    """Read DB_TYPE / DB_CONNECTION_STR / DB_POOL_SIZE from environment.

    - ``DB_TYPE=file`` (or unset) → file backend, no engine.
    - ``DB_TYPE=sqlite`` → SQLite via aiosqlite. Connection string defaults
      to ``sqlite+aiosqlite:///data/ark.db`` if not provided.
    """
    raw_type = os.environ.get("DB_TYPE", "file").strip().lower()
    if raw_type not in ("file", "sqlite"):
        raise ValueError(
            f"Unsupported DB_TYPE={raw_type!r}; expected 'file' or 'sqlite'"
        )

    if raw_type == "file":
        return DBConfig(db_type="file", connection_str="")

    conn = os.environ.get("DB_CONNECTION_STR", "").strip() or _DEFAULT_SQLITE_URL

    pool_raw = os.environ.get("DB_POOL_SIZE", "5").strip()
    try:
        pool_size = int(pool_raw)
    except ValueError as e:
        raise ValueError(
            f"DB_POOL_SIZE must be an integer, got {pool_raw!r}"
        ) from e

    return DBConfig(db_type="sqlite", connection_str=conn, pool_size=pool_size)
