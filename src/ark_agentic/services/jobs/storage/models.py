"""Jobs ORM tables — own DeclarativeBase.

The feature owns its own ``DeclarativeBase`` so ``init_schema()`` here
creates only this feature's tables. No cross-domain ``Base.metadata``
coupling.
"""

from __future__ import annotations

from sqlalchemy import Float, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class JobsBase(DeclarativeBase):
    """Declarative base for jobs feature tables."""


class JobRunRow(JobsBase):
    """One row per (user_id, job_id) — the last-run timestamp.

    Used by ``UserShardScanner`` to skip users already processed today
    after a worker restart. ``job_id`` is globally unique (e.g. concrete
    proactive job names already include the agent identity), so no
    additional ``agent_id`` partitioning is needed.
    """

    __tablename__ = "job_runs"

    user_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    job_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    last_run_at: Mapped[float] = mapped_column(Float)
    updated_at: Mapped[int] = mapped_column(Integer, default=0)
