"""SqliteMemoryRepository — blob strategy.

One row per user holding the full markdown blob in ``user_memory.content``.
Heading-level upsert reuses ``parse_heading_sections`` /
``format_heading_sections`` from ``core.memory.user_profile`` so semantic
behavior matches ``FileMemoryRepository``. Row-level schema (one heading per
row) is deferred until search/scoring needs it.
"""

from __future__ import annotations

import time

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncEngine

from ....db.models import UserMemory
from ....memory.user_profile import (
    format_heading_sections,
    parse_heading_sections,
)


class SqliteMemoryRepository:
    """MemoryRepository over a SQLAlchemy AsyncEngine."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def read(self, user_id: str) -> str:
        async with self._engine.connect() as conn:
            row = (await conn.execute(
                select(UserMemory.content).where(
                    UserMemory.user_id == user_id,
                )
            )).first()
        return row[0] if row else ""

    async def upsert_headings(
        self,
        user_id: str,
        content: str,
    ) -> tuple[list[str], list[str]]:
        """Heading-level upsert. Read-modify-write inside one transaction.

        The merge runs in Python; persistence is a single
        ``INSERT ... ON CONFLICT DO UPDATE`` so two concurrent callers can no
        longer both observe "no row" and race two INSERTs (which would
        otherwise raise IntegrityError on the second commit).
        """
        async with self._engine.begin() as conn:
            row = (await conn.execute(
                select(UserMemory.content).where(
                    UserMemory.user_id == user_id,
                )
            )).first()
            existing = row[0] if row else ""

            prev_preamble, prev_sections = parse_heading_sections(existing)
            _, incoming = parse_heading_sections(content)

            if not incoming:
                return [], []

            merged = {**prev_sections, **incoming}
            new_content = format_heading_sections(prev_preamble, merged)
            now_ms = int(time.time() * 1000)

            stmt = sqlite_insert(UserMemory).values(
                user_id=user_id,
                content=new_content,
                updated_at=now_ms,
            ).on_conflict_do_update(
                index_elements=["user_id"],
                set_={"content": new_content, "updated_at": now_ms},
            )
            await conn.execute(stmt)

        current = [k for k, v in merged.items() if v]
        dropped = sorted(set(prev_sections) - set(current))
        return current, dropped

    async def overwrite(self, user_id: str, content: str) -> None:
        now_ms = int(time.time() * 1000)
        stmt = sqlite_insert(UserMemory).values(
            user_id=user_id,
            content=content,
            updated_at=now_ms,
        ).on_conflict_do_update(
            index_elements=["user_id"],
            set_={"content": content, "updated_at": now_ms},
        )
        async with self._engine.begin() as conn:
            await conn.execute(stmt)

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
        async with self._engine.connect() as conn:
            rows = (await conn.execute(stmt)).all()
        return [r[0] for r in rows]
