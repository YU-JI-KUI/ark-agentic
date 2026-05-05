"""Storage mode selection — env-driven.

Resolves the runtime answer to "how is this deployment persisting data?".
Tier 0 (default): ``DB_TYPE`` unset or ``"file"`` → file backend, no SQL engine.
Tier 1: ``DB_TYPE=sqlite`` → SQLAlchemy + SQLite (future PG/MySQL slot in here).

The env var is named ``DB_TYPE`` for historical compatibility with existing
deployments; semantically it selects the storage *mode*, not just a DB.
"""

from __future__ import annotations

import os
from typing import Literal

StorageMode = Literal["file", "sqlite"]


def current() -> StorageMode:
    """Return the active storage mode parsed from ``DB_TYPE``."""
    raw = os.environ.get("DB_TYPE", "file").strip().lower()
    if raw not in ("file", "sqlite"):
        raise ValueError(
            f"Unsupported DB_TYPE={raw!r}; expected 'file' or 'sqlite'"
        )
    return raw  # type: ignore[return-value]


def is_database() -> bool:
    """True iff a SQL engine should be available (i.e. mode != 'file')."""
    return current() != "file"
