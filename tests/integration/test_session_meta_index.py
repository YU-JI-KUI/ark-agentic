"""Verify the composite ``ix_session_meta_user_updated_at`` index is used.

A regression for it would silently bring back the dashboard slowdown
(full-table scan + temp B-tree sort).
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from ark_agentic.core.storage.database.config import DBConfig
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


async def test_per_user_listing_uses_composite_index():
    cfg = DBConfig(
        db_type="sqlite", connection_str="sqlite+aiosqlite:///:memory:",
    )
    engine = get_async_engine(cfg)
    await init_schema(engine)

    async with engine.connect() as conn:
        rows = (await conn.execute(text(
            "EXPLAIN QUERY PLAN "
            "SELECT session_id FROM session_meta "
            "WHERE user_id = :u ORDER BY updated_at DESC"
        ), {"u": "alice"})).all()

    plan = " | ".join(str(r) for r in rows)

    assert "ix_session_meta_user_updated_at" in plan, plan
    assert "USE TEMP B-TREE" not in plan.upper(), plan
