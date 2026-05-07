"""SqliteStudioUserRepository — Studio role grants over SQLAlchemy.

Owns lazy schema bootstrap (table + seed admin) guarded by an
``asyncio.Lock`` so the FastAPI lifespan eager-init AND ad-hoc test
construction both end up in a consistent state without doing it twice.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from sqlalchemy import and_, delete, func, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.sql import ColumnElement

from ..protocol import (
    LastAdminError,
    StudioRole,
    StudioUserNotFoundError,
    StudioUserPage,
    StudioUserRecord,
    validate_studio_role,
)
from .models import AuthBase, StudioUserRow


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _validate_role(role: str) -> StudioRole:
    return validate_studio_role(role)


def _row_to_record(row) -> StudioUserRecord:
    mapping = row._mapping
    return StudioUserRecord(
        user_id=mapping["user_id"],
        role=_validate_role(mapping["role"]),
        created_at=mapping["created_at"],
        updated_at=mapping["updated_at"],
        created_by=mapping["created_by"],
        updated_by=mapping["updated_by"],
    )


class SqliteStudioUserRepository:
    """StudioUserRepository over a SQLAlchemy AsyncEngine."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine
        self._init_lock = asyncio.Lock()
        self._initialized = False

    async def ensure_schema(self) -> None:
        """Lazy schema bootstrap (alembic + admin seed). Idempotent."""
        if self._initialized:
            return
        async with self._init_lock:
            if self._initialized:
                return
            from pathlib import Path

            from ......core.storage.database.migrate import upgrade_to_head

            migrations_dir = Path(__file__).parent / "migrations"
            await upgrade_to_head(
                metadata=AuthBase.metadata,
                migrations_dir=migrations_dir,
                engine=self._engine,
                version_table="alembic_version_studio_auth",
            )
            await _seed_default_admin(self._engine)
            self._initialized = True

    # ── Read ────────────────────────────────────────────────────

    async def list_users_page(
        self,
        *,
        query: str = "",
        role: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> StudioUserPage:
        await self.ensure_schema()
        clean_query = query.strip()
        clean_role = _validate_role(role) if role else None
        clean_limit = min(max(limit, 1), 200)
        clean_offset = max(offset, 0)

        filters: list[ColumnElement[bool]] = []
        if clean_query:
            filters.append(StudioUserRow.user_id.ilike(f"%{clean_query}%"))
        if clean_role:
            filters.append(StudioUserRow.role == clean_role)
        where_clause = and_(*filters) if filters else None

        count_stmt = select(func.count()).select_from(StudioUserRow)
        list_stmt = select(StudioUserRow).order_by(StudioUserRow.user_id.asc())
        if where_clause is not None:
            count_stmt = count_stmt.where(where_clause)
            list_stmt = list_stmt.where(where_clause)
        list_stmt = list_stmt.limit(clean_limit).offset(clean_offset)

        admin_stmt = (
            select(func.count())
            .select_from(StudioUserRow)
            .where(StudioUserRow.role == "admin")
        )

        async with self._engine.connect() as conn:
            total = (await conn.execute(count_stmt)).scalar_one()
            admin_count = (await conn.execute(admin_stmt)).scalar_one()
            rows = (await conn.execute(list_stmt)).all()

        return StudioUserPage(
            users=[_row_to_record(row) for row in rows],
            total=int(total),
            admin_count=int(admin_count),
            limit=clean_limit,
            offset=clean_offset,
        )

    async def get_user(self, user_id: str) -> StudioUserRecord | None:
        await self.ensure_schema()
        async with self._engine.connect() as conn:
            row = (await conn.execute(
                select(StudioUserRow).where(StudioUserRow.user_id == user_id)
            )).first()
        return _row_to_record(row) if row else None

    # ── Write ───────────────────────────────────────────────────

    async def ensure_user(
        self, user_id: str, *, default_role: StudioRole = "viewer",
    ) -> StudioUserRecord:
        await self.ensure_schema()
        role = _validate_role(default_role)
        now = _utcnow()
        ins = sqlite_insert(StudioUserRow).values(
            user_id=user_id,
            role=role,
            created_at=now,
            updated_at=now,
            created_by="login",
            updated_by="login",
        ).on_conflict_do_nothing(index_elements=["user_id"])

        async with self._engine.begin() as conn:
            await conn.execute(ins)
            row = (await conn.execute(
                select(StudioUserRow).where(StudioUserRow.user_id == user_id)
            )).one()
        return _row_to_record(row)

    async def upsert_user(
        self, user_id: str, role: str, *, actor_user_id: str,
    ) -> StudioUserRecord:
        await self.ensure_schema()
        clean_role = _validate_role(role)
        now = _utcnow()

        async with self._engine.begin() as conn:
            row = (await conn.execute(
                select(StudioUserRow).where(StudioUserRow.user_id == user_id)
            )).first()
            if row:
                current = _row_to_record(row)
                if current.role == "admin" and clean_role != "admin":
                    await self._assert_not_last_admin(conn)
                await conn.execute(
                    update(StudioUserRow)
                    .where(StudioUserRow.user_id == user_id)
                    .values(
                        role=clean_role,
                        updated_at=now,
                        updated_by=actor_user_id,
                    )
                )
            else:
                await conn.execute(sqlite_insert(StudioUserRow).values(
                    user_id=user_id,
                    role=clean_role,
                    created_at=now,
                    updated_at=now,
                    created_by=actor_user_id,
                    updated_by=actor_user_id,
                ))
            next_row = (await conn.execute(
                select(StudioUserRow).where(StudioUserRow.user_id == user_id)
            )).one()
        return _row_to_record(next_row)

    async def delete_user(self, user_id: str) -> None:
        await self.ensure_schema()
        async with self._engine.begin() as conn:
            row = (await conn.execute(
                select(StudioUserRow).where(StudioUserRow.user_id == user_id)
            )).first()
            if not row:
                raise StudioUserNotFoundError(
                    f"User grant not found: {user_id}"
                )
            current = _row_to_record(row)
            if current.role == "admin":
                await self._assert_not_last_admin(conn)
            await conn.execute(
                delete(StudioUserRow).where(StudioUserRow.user_id == user_id)
            )

    # ── Internals ───────────────────────────────────────────────

    async def _assert_not_last_admin(self, conn) -> None:
        admin_count = (await conn.execute(
            select(func.count())
            .select_from(StudioUserRow)
            .where(StudioUserRow.role == "admin")
        )).scalar_one()
        if admin_count <= 1:
            raise LastAdminError("At least one admin is required")


async def _seed_default_admin(engine: AsyncEngine) -> None:
    """Insert the bootstrap ``admin`` row if absent. Idempotent."""
    now = _utcnow()
    async with engine.begin() as conn:
        ins = sqlite_insert(StudioUserRow).values(
            user_id="admin",
            role="admin",
            created_at=now,
            updated_at=now,
            created_by="system",
            updated_by="system",
        ).on_conflict_do_nothing(index_elements=["user_id"])
        await conn.execute(ins)
