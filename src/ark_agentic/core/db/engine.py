"""AsyncEngine factory + schema bootstrap.

PR2: 单进程内对每个 (URL, pool_size) 缓存一个 ``AsyncEngine``。SQLite 默认
启用 WAL pragma 提升并发读写。``init_schema(engine)`` 调用一次性建好所有
注册到 ``Base.metadata`` 的表。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from .base import Base
from .config import DBConfig, load_db_config_from_env

# Make sure all ORM models are imported so they register on Base.metadata
# before init_schema() runs. Import side-effect is intentional.
from . import models  # noqa: F401


def _normalize_sqlite_url(url: str) -> str:
    """Promote sync SQLite URL to aiosqlite if necessary."""
    if url.startswith("sqlite:///") and not url.startswith("sqlite+aiosqlite:///"):
        return "sqlite+aiosqlite:///" + url[len("sqlite:///"):]
    return url


def _sqlite_path_from_url(url: str) -> Path | None:
    if url in {"sqlite:///:memory:", "sqlite+aiosqlite:///:memory:"}:
        return None
    for prefix in ("sqlite+aiosqlite:///", "sqlite:///"):
        if url.startswith(prefix):
            return Path(url[len(prefix):]).expanduser()
    return None


def _enable_sqlite_pragmas_file(dbapi_connection, connection_record) -> None:
    """SQLite connect hook for file-backed DBs — WAL + FK + relaxed sync."""
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA synchronous=NORMAL")
    finally:
        cursor.close()


def _enable_sqlite_pragmas_memory(dbapi_connection, connection_record) -> None:
    """SQLite connect hook for ``:memory:`` — FK only (WAL is a no-op there).

    Without this the ``foreign_keys`` pragma defaults to OFF on every new
    connection and ``:memory:`` test runs silently bypass FK constraints —
    bugs that would crash production go undetected in CI.
    """
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


@lru_cache(maxsize=8)
def _build_engine(connection_str: str, pool_size: int) -> AsyncEngine:
    normalized = _normalize_sqlite_url(connection_str)
    sqlite_path = _sqlite_path_from_url(normalized)
    is_memory_sqlite = (
        normalized.endswith(":memory:")
        and normalized.startswith(("sqlite:", "sqlite+aiosqlite:"))
    )

    if sqlite_path is not None:
        sqlite_path.parent.mkdir(parents=True, exist_ok=True)

    if normalized.startswith("sqlite"):
        engine = create_async_engine(
            normalized,
            future=True,
            connect_args={"check_same_thread": False},
        )
    else:
        engine = create_async_engine(
            normalized, future=True, pool_size=pool_size,
        )

    # FK enforcement must be set per-connection (PRAGMA foreign_keys is not
    # persisted in the DB file). Apply it for every SQLite engine — including
    # ``:memory:`` so tests catch FK violations the same way prod does.
    if normalized.startswith("sqlite"):
        sync_engine: Engine = engine.sync_engine  # type: ignore[attr-defined]
        if is_memory_sqlite:
            event.listen(sync_engine, "connect", _enable_sqlite_pragmas_memory)
        else:
            event.listen(sync_engine, "connect", _enable_sqlite_pragmas_file)

    return engine


def get_async_engine(config: DBConfig | None = None) -> AsyncEngine:
    """Return a process-wide cached AsyncEngine for the given DB config.

    Raises ``RuntimeError`` if called with ``db_type='file'`` — file backend
    has no engine.
    """
    cfg = config or load_db_config_from_env()
    if cfg.db_type == "file":
        raise RuntimeError(
            "get_async_engine() called with DB_TYPE=file; the file backend "
            "does not use a SQLAlchemy engine."
        )
    return _build_engine(cfg.connection_str, cfg.pool_size)


async def init_schema(engine: AsyncEngine) -> None:
    """Create all tables registered on Base.metadata. Idempotent."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def reset_engine_cache() -> None:
    """Clear the engine cache (test helper)."""
    _build_engine.cache_clear()
