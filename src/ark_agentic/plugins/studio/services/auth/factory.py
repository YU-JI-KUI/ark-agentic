"""Studio user-repository factory.

Studio is DB-only (no file backend). ``AsyncEngine`` is encapsulated in
``studio/services/auth/engine.py`` — this factory never sees it.
"""

from __future__ import annotations

from .protocol import StudioUserRepository
from .storage.sqlite import SqliteStudioUserRepository


def build_studio_user_repository() -> StudioUserRepository:
    """Always returns the SQLite implementation."""
    from .engine import get_engine
    return SqliteStudioUserRepository(get_engine())
