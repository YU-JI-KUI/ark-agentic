"""Core repository factories — env-driven backend dispatch.

Tier 0 (default ``DB_TYPE=file``) → file implementations.
Tier 1 (``DB_TYPE=sqlite``) → SQLite implementations sharing one engine.

``AsyncEngine`` is fully encapsulated by ``core.db.engine``: the sqlite
branch asks ``get_engine()`` itself, the file branch only needs paths.
Business code never sees an engine.
"""

from __future__ import annotations

import os
from pathlib import Path

from .repository.file.agent_state import FileAgentStateRepository
from .repository.file.memory import FileMemoryRepository
from .repository.file.session import FileSessionRepository
from .repository.sqlite.agent_state import SqliteAgentStateRepository
from .repository.sqlite.memory import SqliteMemoryRepository
from .repository.sqlite.session import SqliteSessionRepository
from .protocols import (
    AgentStateRepository,
    MemoryRepository,
    SessionRepository,
)
# Re-export the cache accessor so callers don't need to know the adapter
# module name. ``get_cache`` is the singleton entry point.
from .cache_adapter import get_cache  # noqa: F401


def _resolve_db_type() -> str:
    raw = os.environ.get("DB_TYPE", "file").strip().lower()
    if raw not in ("file", "sqlite"):
        raise ValueError(
            f"Unsupported DB_TYPE={raw!r}; expected 'file' or 'sqlite'"
        )
    return raw


def _require_path(path: str | Path | None, what: str, param: str) -> Path:
    if path is None:
        raise ValueError(
            f"{what} requires {param!r} when DB_TYPE=file. "
            f"Either supply {param} or set DB_TYPE=sqlite."
        )
    return Path(path)


def build_session_repository(
    sessions_dir: str | Path | None = None,
) -> SessionRepository:
    db_type = _resolve_db_type()
    if db_type == "file":
        return FileSessionRepository(
            _require_path(sessions_dir, "SessionRepository", "sessions_dir")
        )
    if db_type == "sqlite":
        from ..db.engine import get_engine
        return SqliteSessionRepository(get_engine())
    raise ValueError(f"Unsupported DB_TYPE for session repository: {db_type!r}")


def build_memory_repository(
    workspace_dir: str | Path | None = None,
) -> MemoryRepository:
    db_type = _resolve_db_type()
    if db_type == "file":
        return FileMemoryRepository(
            _require_path(workspace_dir, "MemoryRepository", "workspace_dir")
        )
    if db_type == "sqlite":
        from ..db.engine import get_engine
        return SqliteMemoryRepository(get_engine())
    raise ValueError(f"Unsupported DB_TYPE for memory repository: {db_type!r}")


def build_agent_state_repository(
    workspace_dir: str | Path | None = None,
) -> AgentStateRepository:
    db_type = _resolve_db_type()
    if db_type == "file":
        return FileAgentStateRepository(
            _require_path(workspace_dir, "AgentStateRepository", "workspace_dir")
        )
    if db_type == "sqlite":
        from ..db.engine import get_engine
        return SqliteAgentStateRepository(get_engine())
    raise ValueError(f"Unsupported DB_TYPE for agent state repository: {db_type!r}")
