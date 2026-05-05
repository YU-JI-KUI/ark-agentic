"""MemoryRepository.list_memory_summaries — SQLite + file backends.

Pins the BFF contract: dashboard listing must come from ONE round-trip
per backend (`SELECT user_id, length(content), updated_at` for SQLite,
one `iterdir() + stat()` for file). Test the values, not the mechanism.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ark_agentic.core.storage.database.config import DBConfig
from ark_agentic.core.storage.database.engine import (
    get_async_engine,
    init_schema,
    reset_engine_cache,
)
from ark_agentic.core.storage.database.sqlite.memory import (
    SqliteMemoryRepository,
)
from ark_agentic.core.storage.file.memory import FileMemoryRepository


@pytest.fixture(autouse=True)
def _clean_engine_cache():
    reset_engine_cache()
    yield
    reset_engine_cache()


async def test_sqlite_memory_summaries_returns_size_and_updated_at():
    cfg = DBConfig(
        db_type="sqlite", connection_str="sqlite+aiosqlite:///:memory:",
    )
    engine = get_async_engine(cfg)
    await init_schema(engine)
    repo = SqliteMemoryRepository(engine)
    await repo.overwrite("u1", "## Profile\nname: alice\n")
    await repo.overwrite("u2", "## Profile\nname: bob smith\n")

    rows = await repo.list_memory_summaries()

    by_user = {r.user_id: r for r in rows}
    assert by_user["u1"].size_bytes == len("## Profile\nname: alice\n")
    assert by_user["u2"].size_bytes == len("## Profile\nname: bob smith\n")
    assert by_user["u1"].updated_at is not None


async def test_file_memory_summaries_uses_stat_for_size_and_mtime(
    tmp_path: Path,
):
    repo = FileMemoryRepository(tmp_path)
    await repo.overwrite("u1", "hello\n")

    rows = await repo.list_memory_summaries()

    assert len(rows) == 1
    assert rows[0].user_id == "u1"
    assert rows[0].size_bytes == len(b"hello\n")
    assert rows[0].updated_at is not None
