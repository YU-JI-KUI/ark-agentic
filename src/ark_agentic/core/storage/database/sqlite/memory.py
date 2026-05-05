"""SqliteMemoryRepository — one row per (agent_id, user_id), full markdown blob.

Heading-level upsert reuses ``parse_heading_sections`` /
``format_heading_sections`` so behavior matches ``FileMemoryRepository``.
Bound to one ``agent_id``; reads/writes go through ``agent_scoped_session``.
"""

from __future__ import annotations

import time

from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from ..models import UserMemory
from ..scoping import agent_scoped_session
from ....memory.user_profile import (
    format_heading_sections,
    parse_heading_sections,
)
from ...entries import MemorySummaryEntry


class SqliteMemoryRepository:
    """MemoryRepository over a SQLAlchemy AsyncEngine, bound to one agent."""

    def __init__(self, engine: AsyncEngine, agent_id: str) -> None:
        if not agent_id:
            raise ValueError("SqliteMemoryRepository requires a non-empty agent_id")
        self._engine = engine
        self._agent_id = agent_id
        self._sessionmaker = async_sessionmaker(engine, expire_on_commit=False)

    async def read(self, user_id: str) -> str:
        async with agent_scoped_session(self._sessionmaker, self._agent_id) as s:
            row = await s.scalar(
                select(UserMemory.content).where(
                    UserMemory.user_id == user_id,
                )
            )
        return row or ""

    async def upsert_headings(
        self,
        user_id: str,
        content: str,
    ) -> tuple[list[str], list[str]]:
        """Read-modify-write merge in Python; one ON CONFLICT DO UPDATE
        commits, so concurrent callers don't race two INSERTs."""
        async with agent_scoped_session(self._sessionmaker, self._agent_id) as s:
            existing = await s.scalar(
                select(UserMemory.content).where(
                    UserMemory.user_id == user_id,
                )
            ) or ""

            prev_preamble, prev_sections = parse_heading_sections(existing)
            _, incoming = parse_heading_sections(content)

            if not incoming:
                return [], []

            merged = {**prev_sections, **incoming}
            new_content = format_heading_sections(prev_preamble, merged)
            now_ms = int(time.time() * 1000)

            stmt = sqlite_insert(UserMemory).values(
                agent_id=self._agent_id,
                user_id=user_id,
                content=new_content,
                updated_at=now_ms,
            ).on_conflict_do_update(
                index_elements=["agent_id", "user_id"],
                set_={"content": new_content, "updated_at": now_ms},
            )
            await s.execute(stmt)
            await s.commit()

        current = [k for k, v in merged.items() if v]
        dropped = sorted(set(prev_sections) - set(current))
        return current, dropped

    async def overwrite(self, user_id: str, content: str) -> None:
        now_ms = int(time.time() * 1000)
        stmt = sqlite_insert(UserMemory).values(
            agent_id=self._agent_id,
            user_id=user_id,
            content=content,
            updated_at=now_ms,
        ).on_conflict_do_update(
            index_elements=["agent_id", "user_id"],
            set_={"content": content, "updated_at": now_ms},
        )
        async with agent_scoped_session(self._sessionmaker, self._agent_id) as s:
            await s.execute(stmt)
            await s.commit()

    async def get_last_dream_at(self, user_id: str) -> float | None:
        async with agent_scoped_session(self._sessionmaker, self._agent_id) as s:
            return await s.scalar(
                select(UserMemory.last_dream_at).where(
                    UserMemory.user_id == user_id,
                )
            )

    async def set_last_dream_at(
        self, user_id: str, timestamp: float,
    ) -> None:
        now_ms = int(time.time() * 1000)
        stmt = sqlite_insert(UserMemory).values(
            agent_id=self._agent_id,
            user_id=user_id,
            content="",
            last_dream_at=timestamp,
            updated_at=now_ms,
        ).on_conflict_do_update(
            index_elements=["agent_id", "user_id"],
            set_={"last_dream_at": timestamp, "updated_at": now_ms},
        )
        async with agent_scoped_session(self._sessionmaker, self._agent_id) as s:
            await s.execute(stmt)
            await s.commit()

    async def list_users(
        self,
        limit: int | None = None,
        offset: int = 0,
        order_by_updated_desc: bool = True,
    ) -> list[str]:
        order_col = (
            UserMemory.updated_at.desc()
            if order_by_updated_desc
            else UserMemory.updated_at.asc()
        )
        stmt = select(UserMemory.user_id).order_by(order_col)
        if limit is not None:
            stmt = stmt.limit(limit).offset(offset)
        async with agent_scoped_session(self._sessionmaker, self._agent_id) as s:
            rows = (await s.execute(stmt)).all()
        return [r[0] for r in rows]

    async def list_memory_summaries(
        self,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[MemorySummaryEntry]:
        stmt = (
            select(
                UserMemory.user_id,
                func.length(UserMemory.content).label("size_bytes"),
                UserMemory.updated_at,
            )
            .order_by(UserMemory.updated_at.desc())
        )
        if limit is not None:
            stmt = stmt.limit(limit).offset(offset)
        async with agent_scoped_session(self._sessionmaker, self._agent_id) as s:
            rows = (await s.execute(stmt)).all()
        return [
            MemorySummaryEntry(
                user_id=r.user_id,
                size_bytes=int(r.size_bytes or 0),
                updated_at=r.updated_at,
                file_type="memory",
                path=f"{r.user_id}/MEMORY.md",
            )
            for r in rows
        ]
