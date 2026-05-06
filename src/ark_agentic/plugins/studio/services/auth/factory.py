"""Studio user-repository factory."""

from __future__ import annotations

from pathlib import Path

from .....core.storage import mode
from .protocol import StudioUserRepository
from .storage.file import DEFAULT_STUDIO_AUTH_FILE, FileStudioUserRepository
from .storage.sqlite import SqliteStudioUserRepository


def build_studio_user_repository(
    file_path: str | Path | None = None,
) -> StudioUserRepository:
    """Build the Studio auth repository for the active storage mode."""
    active = mode.current()
    if active == "file":
        return FileStudioUserRepository(file_path or DEFAULT_STUDIO_AUTH_FILE)
    if active == "sqlite":
        from .engine import get_engine

        return SqliteStudioUserRepository(get_engine())
    raise ValueError(
        f"Unsupported storage mode for studio user repository: {active!r}"
    )
