"""Repository factories — env-driven backend dispatch.

Tier 0 (default ``DB_TYPE=file``) → file backends rooted at the supplied paths.
Tier 1 (``DB_TYPE=sqlite``) → SQLite backends sharing a single AsyncEngine.

PR3+ adds postgres / redis / s3 entries here. Business code only sees the
Protocol return type — the wiring is concentrated in this single module.
"""

from __future__ import annotations

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
from ..db.config import load_db_config_from_env


def _resolve_db_type() -> str:
    """Resolve current DB_TYPE; centralized for testability."""
    return load_db_config_from_env().db_type


def _require_engine(engine: AsyncEngine | None, what: str) -> AsyncEngine:
    if engine is None:
        raise RuntimeError(
            f"{what} requested SQLite backend but no AsyncEngine was provided. "
            "Construct the engine in app.lifespan via get_async_engine() and "
            "inject it into the factory call."
        )
    return engine


def build_session_repository(
    sessions_dir: str | Path,
    engine: AsyncEngine | None = None,
) -> SessionRepository:
    db_type = _resolve_db_type()
    if db_type == "file":
        return FileSessionRepository(sessions_dir)
    if db_type == "sqlite":
        return SqliteSessionRepository(_require_engine(engine, "SessionRepository"))
    raise ValueError(f"Unsupported DB_TYPE for session repository: {db_type!r}")


def build_memory_repository(
    workspace_dir: str | Path,
    engine: AsyncEngine | None = None,
) -> MemoryRepository:
    db_type = _resolve_db_type()
    if db_type == "file":
        return FileMemoryRepository(workspace_dir)
    if db_type == "sqlite":
        return SqliteMemoryRepository(_require_engine(engine, "MemoryRepository"))
    raise ValueError(f"Unsupported DB_TYPE for memory repository: {db_type!r}")


def build_agent_state_repository(
    workspace_dir: str | Path,
    engine: AsyncEngine | None = None,
) -> AgentStateRepository:
    db_type = _resolve_db_type()
    if db_type == "file":
        return FileAgentStateRepository(workspace_dir)
    if db_type == "sqlite":
        return SqliteAgentStateRepository(
            _require_engine(engine, "AgentStateRepository")
        )
    raise ValueError(f"Unsupported DB_TYPE for agent state repository: {db_type!r}")


def build_notification_repository(
    base_dir: str | Path,
    engine: AsyncEngine | None = None,
) -> NotificationRepository:
    db_type = _resolve_db_type()
    if db_type == "file":
        return FileNotificationRepository(base_dir)
    if db_type == "sqlite":
        return SqliteNotificationRepository(
            _require_engine(engine, "NotificationRepository")
        )
    raise ValueError(
        f"Unsupported DB_TYPE for notification repository: {db_type!r}"
    )


def build_cache() -> Cache:
    """PR2: Cache is always in-process. PR3 introduces RedisCache via env."""
    return MemoryCache()
