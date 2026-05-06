"""Studio user-grants SQL engine accessor.

When ``DB_TYPE=sqlite`` Studio rides on the central
``core.storage.database`` engine, so ``studio_users`` lives in the same
DB file selected by ``DB_CONNECTION_STR``.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine

# Importing the storage package registers ``StudioUserRow`` on
# the feature-local ``AuthBase.metadata``.
from . import storage  # noqa: F401

_engine: AsyncEngine | None = None
_test_engine: AsyncEngine | None = None


def _build_engine() -> AsyncEngine:
    from .....core.storage import mode
    from .....core.storage.database.engine import get_engine as _core_get_engine

    if not mode.is_database():
        raise RuntimeError(
            "Studio SQL engine is only available when DB_TYPE=sqlite."
        )
    return _core_get_engine()


def get_engine() -> AsyncEngine:
    """Return the shared Studio AsyncEngine; cached for the process lifetime."""
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
