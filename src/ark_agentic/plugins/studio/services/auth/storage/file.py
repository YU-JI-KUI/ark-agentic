"""FileStudioUserRepository — Studio role grants over JSON.

Layout: ``data/ark_studio.json`` by default. The store is a single JSON
document because Studio role grants are small operational metadata, and
mutations are guarded by a file lock plus atomic replacement.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ......core.storage.file._lock import FileLock
from ..protocol import (
    LastAdminError,
    StudioRole,
    StudioUserNotFoundError,
    StudioUserPage,
    StudioUserRecord,
    validate_studio_role,
)

DEFAULT_STUDIO_AUTH_FILE = Path("data/ark_studio.json")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _record_to_dict(record: StudioUserRecord) -> dict[str, Any]:
    return {
        "user_id": record.user_id,
        "role": record.role,
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
        "created_by": record.created_by,
        "updated_by": record.updated_by,
    }


def _datetime_from_value(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        raise ValueError(f"Invalid datetime value: {value!r}")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _record_from_dict(data: Any) -> StudioUserRecord:
    if not isinstance(data, dict):
        raise ValueError("Studio user record must be a JSON object")
    return StudioUserRecord(
        user_id=str(data["user_id"]),
        role=validate_studio_role(str(data["role"])),
        created_at=_datetime_from_value(data["created_at"]),
        updated_at=_datetime_from_value(data["updated_at"]),
        created_by=data.get("created_by"),
        updated_by=data.get("updated_by"),
    )


class FileStudioUserRepository:
    """File-backed implementation of StudioUserRepository."""

    def __init__(self, path: str | Path = DEFAULT_STUDIO_AUTH_FILE) -> None:
        self._path = Path(path)
        self._lock_path = self._path.with_suffix(self._path.suffix + ".lock")
        self._initialized = False

    async def ensure_schema(self) -> None:
        """Create the JSON store and seed the bootstrap admin. Idempotent."""
        if self._initialized:
            return
        async with FileLock(self._lock_path):
            store = await asyncio.to_thread(self._load_store_sync)
            if "admin" not in store:
                now = _utcnow()
                store["admin"] = StudioUserRecord(
                    user_id="admin",
                    role="admin",
                    created_at=now,
                    updated_at=now,
                    created_by="system",
                    updated_by="system",
                )
                await asyncio.to_thread(self._write_store_sync, store)
            elif not self._path.exists():
                await asyncio.to_thread(self._write_store_sync, store)
            self._initialized = True

    async def list_users_page(
        self,
        *,
        query: str = "",
        role: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> StudioUserPage:
        await self.ensure_schema()
        store = await asyncio.to_thread(self._load_store_sync)
        clean_query = query.strip().lower()
        clean_role = validate_studio_role(role) if role else None
        clean_limit = min(max(limit, 1), 200)
        clean_offset = max(offset, 0)

        records = sorted(store.values(), key=lambda record: record.user_id)
        filtered = records
        if clean_query:
            filtered = [
                record for record in filtered
                if clean_query in record.user_id.lower()
            ]
        if clean_role:
            filtered = [
                record for record in filtered
                if record.role == clean_role
            ]

        admin_count = sum(1 for record in records if record.role == "admin")
        page = filtered[clean_offset:clean_offset + clean_limit]
        return StudioUserPage(
            users=page,
            total=len(filtered),
            admin_count=admin_count,
            limit=clean_limit,
            offset=clean_offset,
        )

    async def get_user(self, user_id: str) -> StudioUserRecord | None:
        await self.ensure_schema()
        store = await asyncio.to_thread(self._load_store_sync)
        return store.get(user_id)

    async def ensure_user(
        self,
        user_id: str,
        *,
        default_role: StudioRole = "viewer",
    ) -> StudioUserRecord:
        await self.ensure_schema()
        role = validate_studio_role(default_role)
        async with FileLock(self._lock_path):
            store = await asyncio.to_thread(self._load_store_sync)
            existing = store.get(user_id)
            if existing is not None:
                return existing

            now = _utcnow()
            record = StudioUserRecord(
                user_id=user_id,
                role=role,
                created_at=now,
                updated_at=now,
                created_by="login",
                updated_by="login",
            )
            store[user_id] = record
            await asyncio.to_thread(self._write_store_sync, store)
            return record

    async def upsert_user(
        self,
        user_id: str,
        role: str,
        *,
        actor_user_id: str,
    ) -> StudioUserRecord:
        await self.ensure_schema()
        clean_role = validate_studio_role(role)
        async with FileLock(self._lock_path):
            store = await asyncio.to_thread(self._load_store_sync)
            existing = store.get(user_id)
            if (
                existing is not None
                and existing.role == "admin"
                and clean_role != "admin"
            ):
                self._assert_not_last_admin(store)

            now = _utcnow()
            record = StudioUserRecord(
                user_id=user_id,
                role=clean_role,
                created_at=existing.created_at if existing else now,
                updated_at=now,
                created_by=existing.created_by if existing else actor_user_id,
                updated_by=actor_user_id,
            )
            store[user_id] = record
            await asyncio.to_thread(self._write_store_sync, store)
            return record

    async def delete_user(self, user_id: str) -> None:
        await self.ensure_schema()
        async with FileLock(self._lock_path):
            store = await asyncio.to_thread(self._load_store_sync)
            existing = store.get(user_id)
            if existing is None:
                raise StudioUserNotFoundError(f"User grant not found: {user_id}")
            if existing.role == "admin":
                self._assert_not_last_admin(store)

            del store[user_id]
            await asyncio.to_thread(self._write_store_sync, store)

    def _load_store_sync(self) -> dict[str, StudioUserRecord]:
        if not self._path.exists():
            return {}
        with self._path.open("r", encoding="utf-8") as f:
            raw = json.load(f)
        users = raw.get("users", {}) if isinstance(raw, dict) else {}
        store: dict[str, StudioUserRecord] = {}
        for key, value in users.items():
            record = _record_from_dict(value)
            store[record.user_id or str(key)] = record
        return store

    def _write_store_sync(
        self,
        store: dict[str, StudioUserRecord],
    ) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "users": {
                user_id: _record_to_dict(record)
                for user_id, record in sorted(store.items())
            },
        }
        tmp_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=str(self._path.parent),
                prefix=".ark_studio_",
                suffix=".tmp",
                delete=False,
            ) as tmp:
                json.dump(payload, tmp, indent=2, ensure_ascii=False)
                tmp.write("\n")
                tmp_path = tmp.name
            os.replace(tmp_path, self._path)
        finally:
            if tmp_path is not None:
                try:
                    os.unlink(tmp_path)
                except FileNotFoundError:
                    pass

    @staticmethod
    def _assert_not_last_admin(
        store: dict[str, StudioUserRecord],
    ) -> None:
        admin_count = sum(1 for record in store.values() if record.role == "admin")
        if admin_count <= 1:
            raise LastAdminError("At least one admin is required")
