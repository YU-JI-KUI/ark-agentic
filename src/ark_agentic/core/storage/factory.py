"""Repository factories — env-driven backend dispatch.

Tier 0 (default ``DB_TYPE=file``) → file backends rooted at the supplied paths.
Tier 1 (``DB_TYPE=sqlite``) → SQLite backends sharing a single AsyncEngine.

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

from .backends.file.agent_state import FileAgentStateRepository
from .backends.file.memory import FileMemoryRepository
from .backends.file.memory_cache import MemoryCache
from .backends.file.notification import FileNotificationRepository
from .backends.file.session import FileSessionRepository
from .backends.sqlite.agent_state import SqliteAgentStateRepository
from .backends.sqlite.memory import SqliteMemoryRepository
from .backends.sqlite.notification import SqliteNotificationRepository
from .backends.sqlite.session import SqliteSessionRepository
from .protocols import (
    AgentStateRepository,
    Cache,
    MemoryRepository,
    NotificationRepository,
    SessionRepository,
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
    if engine is None:
        raise RuntimeError(
            f"{what} requested SQLite backend but no AsyncEngine was provided. "
            "Construct the engine in app.lifespan via get_async_engine() and "
            "inject it into the factory call."
        )
    return engine


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


def build_notification_repository(
    base_dir: str | Path | None = None,
    engine: AsyncEngine | None = None,
    agent_id: str = "",
) -> NotificationRepository:
    """Build a notification repository scoped to one ``agent_id``.

    File backend isolates by directory (``base_dir`` already includes the
    agent path); SQLite backend isolates by ``agent_id`` column filtering.
    """
    db_type = _resolve_db_type()
    if db_type == "file":
        return FileNotificationRepository(
            _require_path(base_dir, "NotificationRepository", "base_dir")
        )
    if db_type == "sqlite":
        return SqliteNotificationRepository(
            _require_engine(engine, "NotificationRepository"),
            agent_id=agent_id,
        )
    raise ValueError(
        f"Unsupported DB_TYPE for notification repository: {db_type!r}"
    )


def build_cache() -> Cache:
    """PR2: Cache is always in-process. PR3 introduces RedisCache via env."""
    return MemoryCache()
