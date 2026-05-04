"""Repository factories — env-driven backend dispatch.

Tier 0 (default ``DB_TYPE=file``) → file implementations under ``repository/file``.
Tier 1 (``DB_TYPE=sqlite``) → SQLite implementations under ``repository/sqlite`` sharing one AsyncEngine.

Backend-specific parameters are optional in the signature; the active backend
validates that it received what it needs (``sessions_dir`` etc. for file,
``engine`` for sqlite). This keeps call-sites honest about which arguments
matter for the current ``DB_TYPE`` rather than silently ignoring the rest.

PR3+ adds postgres / redis / s3 entries here. Business code only sees the
Protocol return type — the wiring is concentrated in this single module.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncEngine

from .repository.file.agent_state import FileAgentStateRepository
from .repository.file.memory import FileMemoryRepository
from .inproc_cache import MemoryCache
from .repository.file.session import FileSessionRepository
from .repository.sqlite.agent_state import SqliteAgentStateRepository
from .repository.sqlite.memory import SqliteMemoryRepository
from .repository.sqlite.session import SqliteSessionRepository
from .repository.sqlite.studio_user import SqliteStudioUserRepository
from .protocols import (
    AgentStateRepository,
    Cache,
    MemoryRepository,
    SessionRepository,
    StudioUserRepository,
)


def _resolve_db_type() -> str:
    """Read ``DB_TYPE`` from env without constructing a full DBConfig.

    Skips the Pydantic model build that ``load_db_config_from_env()`` does —
    factories are called frequently and only need the type discriminator.
    """
    raw = os.environ.get("DB_TYPE", "file").strip().lower()
    if raw not in ("file", "sqlite"):
        raise ValueError(
            f"Unsupported DB_TYPE={raw!r}; expected 'file' or 'sqlite'"
        )
    return raw


def _require_engine(engine: AsyncEngine | None, what: str) -> AsyncEngine:
    if engine is not None:
        return engine
    # Fall back to the process-wide cached engine. Callers that have no engine
    # reference (e.g. Scanner) can omit the argument; callers that do (e.g.
    # lifespan) should still pass it explicitly.
    from ..db.engine import get_async_engine
    return get_async_engine()


def _require_path(path: str | Path | None, what: str, param: str) -> Path:
    if path is None:
        raise ValueError(
            f"{what} requires {param!r} when DB_TYPE=file. "
            f"Either supply {param} or set DB_TYPE=sqlite with an engine."
        )
    return Path(path)


def build_session_repository(
    sessions_dir: str | Path | None = None,
    engine: AsyncEngine | None = None,
) -> SessionRepository:
    db_type = _resolve_db_type()
    if db_type == "file":
        return FileSessionRepository(
            _require_path(sessions_dir, "SessionRepository", "sessions_dir")
        )
    if db_type == "sqlite":
        return SqliteSessionRepository(
            _require_engine(engine, "SessionRepository")
        )
    raise ValueError(f"Unsupported DB_TYPE for session repository: {db_type!r}")


def build_memory_repository(
    workspace_dir: str | Path | None = None,
    engine: AsyncEngine | None = None,
) -> MemoryRepository:
    db_type = _resolve_db_type()
    if db_type == "file":
        return FileMemoryRepository(
            _require_path(workspace_dir, "MemoryRepository", "workspace_dir")
        )
    if db_type == "sqlite":
        return SqliteMemoryRepository(_require_engine(engine, "MemoryRepository"))
    raise ValueError(f"Unsupported DB_TYPE for memory repository: {db_type!r}")


def build_agent_state_repository(
    workspace_dir: str | Path | None = None,
    engine: AsyncEngine | None = None,
) -> AgentStateRepository:
    db_type = _resolve_db_type()
    if db_type == "file":
        return FileAgentStateRepository(
            _require_path(workspace_dir, "AgentStateRepository", "workspace_dir")
        )
    if db_type == "sqlite":
        return SqliteAgentStateRepository(
            _require_engine(engine, "AgentStateRepository")
        )
    raise ValueError(f"Unsupported DB_TYPE for agent state repository: {db_type!r}")


def build_cache() -> Cache:
    """PR2: Cache is always in-process. PR3 introduces RedisCache via env."""
    return MemoryCache()


def build_studio_user_repository(
    engine: AsyncEngine,
) -> StudioUserRepository:
    """Studio is DB-only — no file backend exists.

    Always returns the SQLite implementation. The caller decides which
    engine to pass (the central ``core.db`` engine when DB_TYPE=sqlite,
    or a dedicated Studio engine otherwise — see Studio's own bootstrap).
    """
    return SqliteStudioUserRepository(engine)
