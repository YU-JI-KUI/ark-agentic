"""Studio auth storage backend selection."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from ark_agentic.plugins.studio.services.auth.factory import (
    build_studio_user_repository,
)
from ark_agentic.plugins.studio.services.auth.protocol import (
    LastAdminError,
    StudioUserNotFoundError,
)
from ark_agentic.plugins.studio.services.auth.storage.file import (
    FileStudioUserRepository,
)
from ark_agentic.plugins.studio.services.auth.storage.sqlite import (
    SqliteStudioUserRepository,
)


async def test_file_studio_user_repo_persists_to_ark_studio_json(
    tmp_path: Path,
) -> None:
    path = tmp_path / "ark_studio.json"
    repo = FileStudioUserRepository(path)

    await repo.ensure_schema()
    await repo.ensure_schema()

    assert path.is_file()
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["users"]["admin"]["role"] == "admin"

    viewer = await repo.ensure_user("viewer", default_role="viewer")
    assert viewer.role == "viewer"

    page = await repo.list_users_page(query="view", role="viewer")
    assert page.total == 1
    assert page.admin_count == 1
    assert page.users[0].user_id == "viewer"

    editor = await repo.upsert_user(
        "editor",
        "editor",
        actor_user_id="admin",
    )
    assert editor.role == "editor"

    await repo.delete_user("editor")
    with pytest.raises(StudioUserNotFoundError):
        await repo.delete_user("editor")


async def test_file_studio_user_repo_enforces_last_admin(
    tmp_path: Path,
) -> None:
    repo = FileStudioUserRepository(tmp_path / "ark_studio.json")
    await repo.ensure_schema()

    with pytest.raises(LastAdminError):
        await repo.delete_user("admin")

    await repo.upsert_user("backup-admin", "admin", actor_user_id="admin")
    await repo.delete_user("admin")
    assert await repo.get_user("admin") is None
    backup = await repo.get_user("backup-admin")
    assert backup is not None
    assert backup.role == "admin"


async def test_factory_file_mode_returns_json_backend(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("DB_TYPE", "file")
    repo = build_studio_user_repository(tmp_path / "ark_studio.json")

    assert isinstance(repo, FileStudioUserRepository)
    await repo.ensure_schema()
    assert (tmp_path / "ark_studio.json").is_file()


def test_studio_sql_engine_rejects_file_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ark_agentic.plugins.studio.services.auth.engine import (
        get_engine,
        reset_engine_for_testing,
    )

    reset_engine_for_testing()
    monkeypatch.setenv("DB_TYPE", "file")

    try:
        with pytest.raises(RuntimeError, match="DB_TYPE=sqlite"):
            get_engine()
    finally:
        reset_engine_for_testing()


async def test_factory_sqlite_reuses_db_connection_str(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from ark_agentic.core.storage.database.engine import reset_engine_cache
    from ark_agentic.plugins.studio.services.auth.engine import (
        reset_engine_for_testing,
    )

    db_path = tmp_path / "ark.db"
    reset_engine_cache()
    reset_engine_for_testing()
    monkeypatch.setenv("DB_TYPE", "sqlite")
    monkeypatch.setenv(
        "DB_CONNECTION_STR",
        f"sqlite+aiosqlite:///{db_path.as_posix()}",
    )

    try:
        repo = build_studio_user_repository()
        assert isinstance(repo, SqliteStudioUserRepository)

        await repo.ensure_schema()

        assert db_path.is_file()
        with sqlite3.connect(db_path) as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "select name from sqlite_master where type='table'",
                )
            }
        assert "studio_users" in tables
    finally:
        reset_engine_cache()
        reset_engine_for_testing()
