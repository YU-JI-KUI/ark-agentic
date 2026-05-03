"""SqliteAgentStateRepository — composite-PK key/value store.

Schema: ``agent_state(user_id, key)`` PK + ``value`` text + ``updated_at``.
"""

from __future__ import annotations

import time

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncEngine

from ....db.models import AgentState


class SqliteAgentStateRepository:
    """AgentStateRepository over a SQLAlchemy AsyncEngine."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def get(self, user_id: str, key: str) -> str | None:
        async with self._engine.connect() as conn:
            row = (await conn.execute(
                select(AgentState.value).where(
                    AgentState.user_id == user_id,
                    AgentState.key == key,
                )
            )).first()
        return row[0] if row else None

    async def set(self, user_id: str, key: str, value: str) -> None:
        """Single-statement upsert. Removes the SELECT-then-INSERT race."""
        now_ms = int(time.time() * 1000)
        stmt = sqlite_insert(AgentState).values(
            user_id=user_id,
            key=key,
            value=value,
            updated_at=now_ms,
        ).on_conflict_do_update(
            index_elements=["user_id", "key"],
            set_={"value": value, "updated_at": now_ms},
        )
        async with self._engine.begin() as conn:
            await conn.execute(stmt)

    async def list_users_with_key(
        self,
        key: str,
        limit: int | None = None,
        offset: int = 0,
        order_by_updated_desc: bool = True,
    ) -> list[tuple[str, str]]:
        order_col = (
            AgentState.updated_at.desc()
            if order_by_updated_desc
            else AgentState.updated_at.asc()
        )
        stmt = (
            select(AgentState.user_id, AgentState.value)
            .where(AgentState.key == key)
            .order_by(order_col)
        )
        if limit is not None:
            stmt = stmt.limit(limit).offset(offset)
        async with self._engine.connect() as conn:
            rows = (await conn.execute(stmt)).all()
        return [(r[0], r[1]) for r in rows]
