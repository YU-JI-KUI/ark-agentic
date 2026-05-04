"""Studio user-repository factory.

Studio is DB-only (no file backend). Phase 4 will hide ``engine`` behind
a per-domain ``engine.py`` module; for now the caller passes an engine
explicitly.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine

# Importing the storage package as a side-effect registers
# ``StudioUserRow`` on ``core.db.base.Base.metadata``.
from .protocol import StudioUserRepository
from .storage.sqlite import SqliteStudioUserRepository


def build_studio_user_repository(engine: AsyncEngine) -> StudioUserRepository:
    """Always returns the SQLite implementation (the only backend Studio has)."""
    return SqliteStudioUserRepository(engine)
