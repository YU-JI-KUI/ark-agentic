"""Jobs engine accessor + schema initialiser.

Jobs currently shares the central ``core.storage.database`` engine — but the
feature's tables live on its own ``JobsBase.metadata``, so ``init_schema()``
here truly creates only the jobs schema. A future split (dedicated DB,
sharded engine) is a one-file change.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine

# Importing the storage package registers ``JobRunRow`` on
# ``JobsBase.metadata``.
from .storage.models import JobsBase


def get_engine() -> AsyncEngine:
    from ...core.storage.database.engine import get_engine as _core_get_engine
    return _core_get_engine()


async def init_schema() -> None:
    """Create job_runs table only. Idempotent."""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(JobsBase.metadata.create_all)
