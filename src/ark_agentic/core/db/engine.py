"""AsyncEngine factory + schema bootstrap for the core domain.

The engine is owned by this module — business code never sees it. Each
storage domain (core / notifications / studio) has its own ``engine.py``
that exposes ``get_engine()`` and ``init_schema()``; factories internally
ask their domain accessor and never accept ``engine=`` in public APIs.

PR2: process-wide ``AsyncEngine`` cached per (URL, pool_size) via
``@lru_cache``. SQLite enables WAL pragma for file-backed DBs.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from .base import Base
from .config import DBConfig, load_db_config_from_env

# Import core ORM models so they register on this domain's
# ``Base.metadata`` before ``init_schema()`` runs. Each feature owns
# its own ``DeclarativeBase`` and registers its tables independently.
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

    if normalized.startswith("sqlite"):
        sync_engine: Engine = engine.sync_engine  # type: ignore[attr-defined]
        if is_memory_sqlite:
            event.listen(sync_engine, "connect", _enable_sqlite_pragmas_memory)
        else:
            event.listen(sync_engine, "connect", _enable_sqlite_pragmas_file)

    return engine


# Test-injected override; takes precedence over the cache when set.
_test_engine: AsyncEngine | None = None


def get_engine() -> AsyncEngine:
    """Return the process-wide AsyncEngine resolved from the environment.

    Raises ``RuntimeError`` if ``DB_TYPE=file`` — the file backend has no
    engine. Tests can swap the singleton via ``set_engine_for_testing``.
    """
    if _test_engine is not None:
        return _test_engine
    cfg = load_db_config_from_env()
    if cfg.db_type == "file":
        raise RuntimeError(
            "get_engine() called with DB_TYPE=file; the file backend "
            "does not use a SQLAlchemy engine."
        )
    return _build_engine(cfg.connection_str, cfg.pool_size)


def get_async_engine(config: DBConfig | None = None) -> AsyncEngine:
    """Backward-compat shim; prefer ``get_engine()``."""
    if config is None:
        return get_engine()
    if _test_engine is not None:
        return _test_engine
    if config.db_type == "file":
        raise RuntimeError(
            "get_async_engine() called with DB_TYPE=file; the file backend "
            "does not use a SQLAlchemy engine."
        )
    return _build_engine(config.connection_str, config.pool_size)


async def init_schema(engine: AsyncEngine | None = None) -> None:
    """Create core tables (sessions / user memory). Idempotent.

    Each independent feature has its own ``init_schema()`` against its
    own ``DeclarativeBase.metadata`` — they are NOT created here.

    Without arguments, uses the domain engine via ``get_engine()``.
    Passing an explicit engine is supported for tests / migration tools.
    """
    target = engine if engine is not None else get_engine()
    async with target.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def set_engine_for_testing(engine: AsyncEngine) -> None:
    """Inject a per-test engine; ``get_engine()`` returns it until reset."""
    global _test_engine
    _test_engine = engine


def reset_engine_for_testing() -> None:
    """Drop the per-test engine + clear the cache. Test cleanup helper."""
    global _test_engine
    _test_engine = None
    _build_engine.cache_clear()


def reset_engine_cache() -> None:
    """Backward-compat alias of ``reset_engine_for_testing``."""
    reset_engine_for_testing()
