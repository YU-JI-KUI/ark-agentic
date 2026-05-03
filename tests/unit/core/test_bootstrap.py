"""Unit tests for core.bootstrap."""

from __future__ import annotations

import pytest

from ark_agentic.core.db.engine import reset_engine_cache


async def test_bootstrap_storage_file_backend(monkeypatch):
    from ark_agentic.core.bootstrap import bootstrap_storage
    monkeypatch.setenv("DB_TYPE", "file")
    result = await bootstrap_storage()
    assert result.db_engine is None


async def test_bootstrap_storage_sqlite_backend(monkeypatch, tmp_path):
    from ark_agentic.core.bootstrap import bootstrap_storage
    reset_engine_cache()
    try:
        monkeypatch.setenv("DB_TYPE", "sqlite")
        monkeypatch.setenv("DB_CONNECTION_STR", f"sqlite+aiosqlite:///{tmp_path}/boot.db")
        result = await bootstrap_storage()
        assert result.db_engine is not None
    finally:
        reset_engine_cache()
        monkeypatch.delenv("DB_TYPE", raising=False)
        monkeypatch.delenv("DB_CONNECTION_STR", raising=False)
