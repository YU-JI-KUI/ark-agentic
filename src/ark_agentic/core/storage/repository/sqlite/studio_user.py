"""SqliteStudioUserRepository — Studio role grants over SQLAlchemy.

Implementation lifted from ``studio.services.authz_service.StudioUserStore``.

The repository owns lazy schema bootstrap (table + seed admin) guarded by an
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

from ....db.base import Base
from ....db.models import StudioUser
from ...protocols.studio_user import (
    InvalidStudioRoleError,
    LastAdminError,
    StudioRole,
    StudioUserNotFoundError,
    StudioUserPage,
    StudioUserRecord,
    VALID_STUDIO_ROLES,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _validate_role(role: str) -> StudioRole:
    if role not in VALID_STUDIO_ROLES:
        raise InvalidStudioRoleError(f"Unsupported role: {role}")
    return role  # type: ignore[return-value]


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

    async def _ensure_schema(self) -> None:
        """Lazy schema bootstrap. Idempotent across concurrent callers."""
        if self._initialized:
            return
        async with self._init_lock:
            if self._initialized:
                return
            async with self._engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            await _seed_default_admin(self._engine)
            self._initialized = True

    async def ensure_schema(self) -> None:
        """Public alias for the lazy schema bootstrap. Idempotent."""
        await self._ensure_schema()

    # ── Read ────────────────────────────────────────────────────

    async def list_users_page(
        self,
        *,
        query: str = "",
        role: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> StudioUserPage:
        await self._ensure_schema()
        clean_query = query.strip()
        clean_role = _validate_role(role) if role else None
        clean_limit = min(max(limit, 1), 200)
        clean_offset = max(offset, 0)

        filters: list[ColumnElement[bool]] = []
        if clean_query:
            filters.append(StudioUser.user_id.ilike(f"%{clean_query}%"))
        if clean_role:
            filters.append(StudioUser.role == clean_role)
        where_clause = and_(*filters) if filters else None

        count_stmt = select(func.count()).select_from(StudioUser)
        list_stmt = select(StudioUser).order_by(StudioUser.user_id.asc())
        if where_clause is not None:
            count_stmt = count_stmt.where(where_clause)
            list_stmt = list_stmt.where(where_clause)
        list_stmt = list_stmt.limit(clean_limit).offset(clean_offset)

        admin_stmt = (
            select(func.count())
            .select_from(StudioUser)
            .where(StudioUser.role == "admin")
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
        await self._ensure_schema()
        async with self._engine.connect() as conn:
            row = (await conn.execute(
                select(StudioUser).where(StudioUser.user_id == user_id)
            )).first()
        return _row_to_record(row) if row else None

    # ── Write ───────────────────────────────────────────────────

    async def ensure_user(
        self, user_id: str, *, default_role: StudioRole = "viewer",
    ) -> StudioUserRecord:
        await self._ensure_schema()
        role = _validate_role(default_role)
        now = _utcnow()
        # ON CONFLICT DO NOTHING — first writer wins; subsequent calls get
        # the existing record without an extra round-trip race.
        ins = sqlite_insert(StudioUser).values(
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
                select(StudioUser).where(StudioUser.user_id == user_id)
            )).one()
        return _row_to_record(row)

    async def upsert_user(
        self, user_id: str, role: str, *, actor_user_id: str,
    ) -> StudioUserRecord:
        await self._ensure_schema()
        clean_role = _validate_role(role)
        now = _utcnow()

        async with self._engine.begin() as conn:
            row = (await conn.execute(
                select(StudioUser).where(StudioUser.user_id == user_id)
            )).first()
            if row:
                current = _row_to_record(row)
                if current.role == "admin" and clean_role != "admin":
                    await self._assert_not_last_admin(conn)
                await conn.execute(
                    update(StudioUser)
                    .where(StudioUser.user_id == user_id)
                    .values(
                        role=clean_role,
                        updated_at=now,
                        updated_by=actor_user_id,
                    )
                )
            else:
                await conn.execute(sqlite_insert(StudioUser).values(
                    user_id=user_id,
                    role=clean_role,
                    created_at=now,
                    updated_at=now,
                    created_by=actor_user_id,
                    updated_by=actor_user_id,
                ))
            next_row = (await conn.execute(
                select(StudioUser).where(StudioUser.user_id == user_id)
            )).one()
        return _row_to_record(next_row)

    async def delete_user(self, user_id: str) -> None:
        await self._ensure_schema()
        async with self._engine.begin() as conn:
            row = (await conn.execute(
                select(StudioUser).where(StudioUser.user_id == user_id)
            )).first()
            if not row:
                raise StudioUserNotFoundError(
                    f"User grant not found: {user_id}"
                )
            current = _row_to_record(row)
            if current.role == "admin":
                await self._assert_not_last_admin(conn)
            await conn.execute(
                delete(StudioUser).where(StudioUser.user_id == user_id)
            )

    # ── Internals ───────────────────────────────────────────────

    async def _assert_not_last_admin(self, conn) -> None:
        admin_count = (await conn.execute(
            select(func.count())
            .select_from(StudioUser)
            .where(StudioUser.role == "admin")
        )).scalar_one()
        if admin_count <= 1:
            raise LastAdminError("At least one admin is required")


# ── Bootstrap ─────────────────────────────────────────────────────


async def _seed_default_admin(engine: AsyncEngine) -> None:
    """Insert the bootstrap ``admin`` row if absent. Idempotent."""
    now = _utcnow()
    async with engine.begin() as conn:
        ins = sqlite_insert(StudioUser).values(
            user_id="admin",
            role="admin",
            created_at=now,
            updated_at=now,
            created_by="system",
            updated_by="system",
        ).on_conflict_do_nothing(index_elements=["user_id"])
        await conn.execute(ins)


async def seed_default_admin(repo: SqliteStudioUserRepository) -> None:
    """Public bootstrap helper — calls into the lazy-init path so callers
    don't have to know whether the table exists yet."""
    await repo._ensure_schema()
