"""Studio user-repository singleton accessor + lifespan helpers.

When ``DB_TYPE=sqlite`` Studio rides on the central ``core.db`` engine so
``studio_users`` lives in the same DB file as business tables. Otherwise
a dedicated SQLite engine is created against ``data/ark_studio.db``.

Phase 4 will replace ``_resolve_studio_engine()`` with a per-domain
``engine.py`` module — the singleton accessor will then go through
``build_studio_user_repository()`` without engine plumbing visible here.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from .factory import build_studio_user_repository
from .protocol import StudioUserRepository

DEFAULT_STUDIO_DB_PATH = Path("data/ark_studio.db")


def _resolve_studio_engine() -> AsyncEngine:
    """Pick the AsyncEngine for the Studio repository singleton."""
    db_type = os.environ.get("DB_TYPE", "file").strip().lower()
    if db_type == "sqlite":
        from ....core.db.engine import get_async_engine

        return get_async_engine()

    DEFAULT_STUDIO_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return create_async_engine(
        f"sqlite+aiosqlite:///{DEFAULT_STUDIO_DB_PATH.as_posix()}",
        future=True,
        connect_args={"check_same_thread": False},
    )


@dataclass
class _StudioState:
    repo: StudioUserRepository | None = None
    initialized: bool = False


_state = _StudioState()
_init_lock = asyncio.Lock()


def get_studio_user_repo() -> StudioUserRepository:
    """Module-level singleton accessor.

    Lifespan calls ``ensure_studio_schema()`` at startup so the schema +
    bootstrap admin row are present before the first request.
    """
    if _state.repo is None:
        _state.repo = build_studio_user_repository(_resolve_studio_engine())
    return _state.repo


def set_studio_user_repo_for_testing(repo: StudioUserRepository) -> None:
    """Inject a per-test repository (bypasses engine resolution)."""
    global _state
    _state = _StudioState(repo=repo, initialized=True)


async def ensure_studio_schema() -> None:
    """Create studio_users table (if needed) and seed the bootstrap admin.

    Safe to call repeatedly; double-checked-locking guards the seed insert.
    Lifespan calls this exactly once at startup.
    """
    if _state.initialized:
        return
    async with _init_lock:
        if _state.initialized:
            return
        repo = get_studio_user_repo()
        await repo.ensure_schema()
        _state.initialized = True


def reset_studio_user_repo_cache() -> None:
    """Test helper — drop the singleton + initialization marker."""
    global _state
    _state = _StudioState()
