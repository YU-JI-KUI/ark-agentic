"""CoreStorageLifecycle — core SQL schema bootstrap as a Lifecycle component.

Storage is a **core capability**, not a plugin: every database-backed
deployment needs the central session / user-memory tables before any
plugin can serve requests. The component nature is purely about
lifecycle orchestration — it lets ``Bootstrap`` run alembic
``upgrade head`` for the core metadata alongside the rest of the
application without ``app.py`` hand-rolling that call.

Phases:
  init    — run alembic upgrade head against ``Base.metadata`` when the
            deployment uses a SQL backend (``DB_TYPE != "file"``).
            Idempotent. No-op for file-backed deployments.
  start   — no-op (no runtime context to publish).
  stop    — no-op (engine lifecycle is owned by ``database.engine``).

Auto-loaded by ``Bootstrap`` ahead of ``AgentsLifecycle`` so by the time
agents warm up — and by the time any plugin's ``init`` runs — the
core tables already exist.
"""

from __future__ import annotations

import logging
from typing import Any

from .mode import is_database
from ..protocol.lifecycle import BaseLifecycle

logger = logging.getLogger(__name__)


class CoreStorageLifecycle(BaseLifecycle):
    """Run core schema migrations on startup."""

    name = "core_storage"

    async def init(self) -> None:
        if not is_database():
            return
        from .database.engine import init_schema

        await init_schema()
        logger.debug("Core storage schema migrated to head")
