"""Unit tests for storage factory engine fallback."""

from __future__ import annotations

import pytest

from ark_agentic.core.storage.database.engine import reset_engine_cache


async def test_build_memory_repository_sqlite_without_explicit_engine(monkeypatch, tmp_path):
    """Factory must not raise when engine=None in sqlite mode — use global engine."""
    from ark_agentic.core.storage.database.config import DBConfig
    from ark_agentic.core.storage.database.engine import get_async_engine, init_schema
    from ark_agentic.core.storage.factory import build_memory_repository

    reset_engine_cache()
    try:
        monkeypatch.setenv("DB_TYPE", "sqlite")
        monkeypatch.setenv("DB_CONNECTION_STR", f"sqlite+aiosqlite:///{tmp_path}/factory_test.db")

        cfg = DBConfig(connection_str=f"sqlite+aiosqlite:///{tmp_path}/factory_test.db")
        engine = get_async_engine(cfg)
        await init_schema(engine)

        repo = build_memory_repository(workspace_dir=tmp_path)
        assert repo is not None
    finally:
        reset_engine_cache()
        monkeypatch.delenv("DB_TYPE", raising=False)
        monkeypatch.delenv("DB_CONNECTION_STR", raising=False)
