"""Core repository factories — mode-driven backend dispatch.

Every repo is bound to one ``agent_id``: file mode partitions by path,
SQLite mode auto-injects ``WHERE agent_id = ?``. Empty ``agent_id`` is
rejected.
"""

from __future__ import annotations

from pathlib import Path

from . import mode
from .file.memory import FileMemoryRepository
from .file.session import FileSessionRepository
from .database.sqlite.memory import SqliteMemoryRepository
from .database.sqlite.session import SqliteSessionRepository
from .protocols import MemoryRepository, SessionRepository


def _require_path(path: str | Path | None, what: str, param: str) -> Path:
    if path is None:
        raise ValueError(
            f"{what} requires {param!r} when DB_TYPE=file. "
            f"Either supply {param} or set DB_TYPE=sqlite."
        )
    return Path(path)


def _require_agent_id(agent_id: str | None, what: str) -> str:
    if not agent_id:
        raise ValueError(
            f"{what} requires a non-empty agent_id — every repository "
            "is bound to one agent at construction."
        )
    return agent_id


def build_session_repository(
    sessions_dir: str | Path | None = None,
    *,
    agent_id: str,
) -> SessionRepository:
    aid = _require_agent_id(agent_id, "SessionRepository")
    active = mode.current()
    if active == "file":
        return FileSessionRepository(
            _require_path(sessions_dir, "SessionRepository", "sessions_dir")
        )
    if active == "sqlite":
        from .database.engine import get_engine
        return SqliteSessionRepository(get_engine(), aid)
    raise ValueError(f"Unsupported storage mode: {active!r}")


def build_memory_repository(
    workspace_dir: str | Path | None = None,
    *,
    agent_id: str,
) -> MemoryRepository:
    aid = _require_agent_id(agent_id, "MemoryRepository")
    active = mode.current()
    if active == "file":
        return FileMemoryRepository(
            _require_path(workspace_dir, "MemoryRepository", "workspace_dir")
        )
    if active == "sqlite":
        from .database.engine import get_engine
        return SqliteMemoryRepository(get_engine(), aid)
    raise ValueError(f"Unsupported storage mode: {active!r}")
