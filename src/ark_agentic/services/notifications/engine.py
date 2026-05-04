"""Notifications engine accessor.

Notifications currently shares the central ``core.db`` engine — but
business code goes through this module so a future split (dedicated DB
or sharded engine) is a one-file change. ``init_schema`` is intentionally
empty: ``NotificationRow`` registers on the shared ``Base.metadata`` and
``core.db.engine.init_schema`` already creates it. Kept as a hook point
so the bootstrap can call every domain's ``init_schema`` symmetrically.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine

# Importing the storage package registers ``NotificationRow`` on
# ``core.db.base.Base.metadata`` so the central ``init_schema`` covers it.
from . import storage  # noqa: F401


def get_engine() -> AsyncEngine:
    from ...core.db.engine import get_engine as _core_get_engine
    return _core_get_engine()


async def init_schema() -> None:
    """No-op: tables register on the shared ``Base.metadata``."""
    return None
