"""Studio user-grants engine accessor.

When ``DB_TYPE=sqlite`` Studio rides on the central ``core.storage.database`` engine so
``studio_users`` lives in the same DB file as business tables. Otherwise
a dedicated SQLite engine is created against ``data/ark_studio.db``.

``AsyncEngine`` is fully encapsulated here — repo_singleton / factory
never see it.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

# Importing the storage package registers ``StudioUserRow`` on
# the feature-local ``AuthBase.metadata``.
from . import storage  # noqa: F401

DEFAULT_STUDIO_DB_PATH = Path("data/ark_studio.db")

_engine: AsyncEngine | None = None
_test_engine: AsyncEngine | None = None


def _build_engine() -> AsyncEngine:
    from .....core.storage import mode
    if mode.is_database():
        from .....core.storage.database.engine import get_engine as _core_get_engine
        return _core_get_engine()

    DEFAULT_STUDIO_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return create_async_engine(
        f"sqlite+aiosqlite:///{DEFAULT_STUDIO_DB_PATH.as_posix()}",
        future=True,
        connect_args={"check_same_thread": False},
    )


def get_engine() -> AsyncEngine:
    """Return the Studio AsyncEngine; cached for the process lifetime."""
    global _engine
    if _test_engine is not None:
        return _test_engine
    if _engine is None:
        _engine = _build_engine()
    return _engine


async def init_schema() -> None:
    """Create studio_users + seed bootstrap admin via the repo singleton."""
    from .repo_singleton import ensure_studio_schema
    await ensure_studio_schema()


def set_engine_for_testing(engine: AsyncEngine) -> None:
    global _test_engine
    _test_engine = engine


def reset_engine_for_testing() -> None:
    global _engine, _test_engine
    _engine = None
    _test_engine = None
