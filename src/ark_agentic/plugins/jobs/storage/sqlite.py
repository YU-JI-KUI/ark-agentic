"""SqliteJobRunRepository — composite-PK (user_id, job_id) timestamp store."""

from __future__ import annotations

import time

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncEngine

from .models import JobRunRow


class SqliteJobRunRepository:
    """JobRunRepository over a SQLAlchemy AsyncEngine."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def get_last_run(
        self, user_id: str, job_id: str,
    ) -> float | None:
        async with self._engine.connect() as conn:
            row = (await conn.execute(
                select(JobRunRow.last_run_at).where(
                    JobRunRow.user_id == user_id,
                    JobRunRow.job_id == job_id,
                )
            )).first()
        return row[0] if row else None

    async def set_last_run(
        self, user_id: str, job_id: str, timestamp: float,
    ) -> None:
        """Single-statement upsert keyed on (user_id, job_id)."""
        now_ms = int(time.time() * 1000)
        stmt = sqlite_insert(JobRunRow).values(
            user_id=user_id,
            job_id=job_id,
            last_run_at=timestamp,
            updated_at=now_ms,
        ).on_conflict_do_update(
            index_elements=["user_id", "job_id"],
            set_={"last_run_at": timestamp, "updated_at": now_ms},
        )
        async with self._engine.begin() as conn:
            await conn.execute(stmt)
