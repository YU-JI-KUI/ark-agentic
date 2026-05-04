"""Studio user-repository singleton accessor + lifespan helpers.

The factory + ``engine.py`` own backend selection; this module only
caches the repo and bootstraps schema once at startup.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from .factory import build_studio_user_repository
from .protocol import StudioUserRepository


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
        _state.repo = build_studio_user_repository()
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
