"""Unit tests for SqliteStudioUserRepository."""

from __future__ import annotations

import pytest

from ark_agentic.core.storage.database.config import DBConfig
from ark_agentic.core.storage.database.engine import get_async_engine, init_schema, reset_engine_cache
from ark_agentic.plugins.studio.services.auth.storage.sqlite import SqliteStudioUserRepository


async def test_ensure_schema_is_public_and_idempotent(tmp_path):
    reset_engine_cache()
    try:
        cfg = DBConfig(connection_str=f"sqlite+aiosqlite:///{tmp_path}/test.db")
        engine = get_async_engine(cfg)
        repo = SqliteStudioUserRepository(engine)

        await repo.ensure_schema()
        await repo.ensure_schema()  # idempotent
    finally:
        reset_engine_cache()
