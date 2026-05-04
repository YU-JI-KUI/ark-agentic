"""Unit tests for core.bootstrap."""

from __future__ import annotations

from ark_agentic.core.db.engine import reset_engine_cache


async def test_bootstrap_storage_file_backend(monkeypatch):
    """File mode: bootstrap is a no-op for core / notifications, but still
    runs the studio init (uses its own engine)."""
    from ark_agentic.core.bootstrap import bootstrap_storage
    monkeypatch.setenv("DB_TYPE", "file")
    # No exception is the success criterion; the function returns None.
    assert await bootstrap_storage() is None


async def test_bootstrap_storage_sqlite_backend(monkeypatch, tmp_path):
    from ark_agentic.core.bootstrap import bootstrap_storage
    reset_engine_cache()
    try:
        monkeypatch.setenv("DB_TYPE", "sqlite")
        monkeypatch.setenv(
            "DB_CONNECTION_STR", f"sqlite+aiosqlite:///{tmp_path}/boot.db",
        )
        # SQLite mode runs every domain's init_schema; success = no raise.
        assert await bootstrap_storage() is None
    finally:
        reset_engine_cache()
        monkeypatch.delenv("DB_TYPE", raising=False)
        monkeypatch.delenv("DB_CONNECTION_STR", raising=False)
