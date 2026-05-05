"""Core repository factories — mode-driven backend dispatch.

``mode.current()`` decides whether the file or database backend is active.
``AsyncEngine`` is fully encapsulated by ``database.engine``: the database
branch asks ``get_engine()`` itself, the file branch only needs paths.
Business code never sees an engine.
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


def build_session_repository(
    sessions_dir: str | Path | None = None,
) -> SessionRepository:
    """Build the session repository for the active storage mode.

    SessionManager keeps an in-memory mirror of active sessions, so a
    process cache layer here would be redundant in single-worker mode.
    Multi-worker / Redis is deferred to the PG/Redis milestone.
    """
    active = mode.current()
    if active == "file":
        return FileSessionRepository(
            _require_path(sessions_dir, "SessionRepository", "sessions_dir")
        )
    if active == "sqlite":
        from .database.engine import get_engine
        return SqliteSessionRepository(get_engine())
    raise ValueError(f"Unsupported storage mode: {active!r}")


def build_memory_repository(
    workspace_dir: str | Path | None = None,
) -> MemoryRepository:
    """Build the memory repository for the active storage mode.

    MemoryManager keeps an in-memory mirror of recently-read user memory,
    same shape as SessionManager._sessions; the repo layer is straight
    pass-through to file/sqlite.
    """
    active = mode.current()
    if active == "file":
        return FileMemoryRepository(
            _require_path(workspace_dir, "MemoryRepository", "workspace_dir")
        )
    if active == "sqlite":
        from .database.engine import get_engine
        return SqliteMemoryRepository(get_engine())
    raise ValueError(f"Unsupported storage mode: {active!r}")
