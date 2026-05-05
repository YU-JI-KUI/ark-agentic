"""DBConfig parsing + engine cache + init_schema tests."""

from __future__ import annotations

import pytest
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncEngine

from ark_agentic.core.storage.database.config import (
    DBConfig,
    load_db_config_from_env,
)
from ark_agentic.core.storage.database.engine import (
    get_async_engine,
    init_schema,
    reset_engine_cache,
)


@pytest.fixture(autouse=True)
def _clean_engine_cache():
    reset_engine_cache()
    yield
    reset_engine_cache()


def test_load_config_defaults_to_default_sqlite_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DB_CONNECTION_STR", raising=False)

    cfg = load_db_config_from_env()

    assert cfg.connection_str == "sqlite+aiosqlite:///data/ark.db"


def test_load_config_explicit_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DB_CONNECTION_STR", "sqlite+aiosqlite:///:memory:")

    cfg = load_db_config_from_env()

    assert cfg.connection_str == "sqlite+aiosqlite:///:memory:"


def test_load_config_invalid_pool_size_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DB_POOL_SIZE", "not-a-number")

    with pytest.raises(ValueError, match="DB_POOL_SIZE"):
        load_db_config_from_env()


def test_get_async_engine_caches_per_url() -> None:
    cfg = DBConfig(connection_str="sqlite+aiosqlite:///:memory:")

    e1 = get_async_engine(cfg)
    e2 = get_async_engine(cfg)

    assert e1 is e2
    assert isinstance(e1, AsyncEngine)


def test_get_async_engine_normalizes_sync_sqlite_url() -> None:
    cfg = DBConfig(connection_str="sqlite:///:memory:")

    engine = get_async_engine(cfg)

    assert "aiosqlite" in str(engine.url)


async def test_init_schema_creates_core_tables() -> None:
    """``database.engine.init_schema`` only covers core's own tables.

    Each independent feature has its own ``DeclarativeBase`` and its
    own ``init_schema`` (see ``plugins.notifications.engine``,
    ``plugins.studio.services.auth.engine``).
    """
    cfg = DBConfig(connection_str="sqlite+aiosqlite:///:memory:")
    engine = get_async_engine(cfg)

    await init_schema(engine)

    async with engine.connect() as conn:
        names = await conn.run_sync(
            lambda sync_conn: set(inspect(sync_conn).get_table_names())
        )

    # Core-only tables present.
    assert {
        "session_meta",
        "session_messages",
        "user_memory",
    }.issubset(names)
    # Feature tables NOT created by core's init_schema.
    assert "notifications" not in names
    assert "studio_users" not in names
    assert "job_runs" not in names


def test_reset_engine_cache_returns_fresh_engine() -> None:
    cfg = DBConfig(connection_str="sqlite+aiosqlite:///:memory:")
    e1 = get_async_engine(cfg)

    reset_engine_cache()
    e2 = get_async_engine(cfg)

    assert e1 is not e2
