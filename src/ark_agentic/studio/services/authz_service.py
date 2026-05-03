"""Studio user authorization store and signed-token helpers.

PR1: ``AsyncEngine`` + ``aiosqlite`` migration so it runs inside FastAPI's
event loop. Schema creation + admin seeding fold into a single lazy
``_ensure_schema()`` step guarded by ``asyncio.Lock``.

PR2: ``studio_users`` now lives in ``core.db.models`` so it shares the
project-wide ``Base.metadata`` with other ORM tables. When ``DB_TYPE=sqlite``
this store reuses the central engine (single ``data/ark.db`` file). The
legacy ``STUDIO_DATABASE_URL`` env path remains as a back-compat tier for
deployments that haven't migrated yet.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import Depends, Header, HTTPException
from sqlalchemy import and_, func, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ...core.db.base import Base
from ...core.db.models import StudioUser

logger = logging.getLogger(__name__)

StudioRole = Literal["admin", "editor", "viewer"]
VALID_STUDIO_ROLES: set[str] = {"admin", "editor", "viewer"}
DEFAULT_DATABASE_URL = "sqlite+aiosqlite:///data/ark_studio.db"
DEFAULT_TOKEN_TTL_SECONDS = 43_200


# PR2: Table now declared in ``core.db.models``. Re-export the names that
# downstream code / tests previously imported from this module.
metadata = Base.metadata
studio_users = StudioUser.__table__


@dataclass(frozen=True)
class StudioUserRecord:
    user_id: str
    role: StudioRole
    created_at: datetime
    updated_at: datetime
    created_by: str | None = None
    updated_by: str | None = None


@dataclass(frozen=True)
class StudioUserPage:
    users: list[StudioUserRecord]
    total: int
    admin_count: int
    limit: int
    offset: int


@dataclass(frozen=True)
class StudioPrincipal:
    user_id: str
    role: StudioRole


class StudioAuthzError(Exception):
    """Base class for expected Studio authorization store errors."""


class InvalidStudioRoleError(StudioAuthzError):
    """Raised when an unsupported Studio role is requested."""


class LastAdminError(StudioAuthzError):
    """Raised when a change would remove the last Studio admin."""


class StudioUserNotFoundError(StudioAuthzError):
    """Raised when deleting or loading a missing Studio authorization row."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _validate_role(role: str) -> StudioRole:
    if role not in VALID_STUDIO_ROLES:
        raise InvalidStudioRoleError(f"Unsupported role: {role}")
    return role  # type: ignore[return-value]


def _normalize_async_url(database_url: str) -> str:
    """Promote sync SQLite URL to aiosqlite if necessary."""
    if database_url.startswith("sqlite:///") and not database_url.startswith(
        "sqlite+aiosqlite:///"
    ):
        return "sqlite+aiosqlite:///" + database_url[len("sqlite:///"):]
    return database_url


def _sqlite_path_from_url(database_url: str) -> Path | None:
    if database_url in {"sqlite:///:memory:", "sqlite+aiosqlite:///:memory:"}:
        return None
    for prefix in ("sqlite+aiosqlite:///", "sqlite:///"):
        if database_url.startswith(prefix):
            return Path(database_url[len(prefix):]).expanduser()
    return None


def _create_engine(database_url: str) -> AsyncEngine:
    normalized = _normalize_async_url(database_url)
    sqlite_path = _sqlite_path_from_url(normalized)
    if sqlite_path is not None:
        sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        return create_async_engine(
            normalized,
            future=True,
            connect_args={"check_same_thread": False},
        )
    return create_async_engine(normalized, future=True)


class StudioUserStore:
    """SQLAlchemy AsyncEngine store for Studio role grants."""

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine
        self._lock = asyncio.Lock()
        self._initialized = False

    def _row_to_record(self, row) -> StudioUserRecord:
        mapping = row._mapping
        role = _validate_role(mapping["role"])
        return StudioUserRecord(
            user_id=mapping["user_id"],
            role=role,
            created_at=mapping["created_at"],
            updated_at=mapping["updated_at"],
            created_by=mapping["created_by"],
            updated_by=mapping["updated_by"],
        )

    async def _ensure_schema(self) -> None:
        """Lazily create tables and seed the admin row.

        Uses a double-checked ``asyncio.Lock`` so concurrent first-use
        coroutines do not race the seed insert.
        """
        if self._initialized:
            return
        async with self._lock:
            if self._initialized:
                return
            async with self.engine.begin() as conn:
                await conn.run_sync(metadata.create_all)
                exists = (await conn.execute(
                    select(studio_users.c.user_id).where(
                        studio_users.c.user_id == "admin"
                    )
                )).first()
                if not exists:
                    now = _utcnow()
                    await conn.execute(insert(studio_users).values(
                        user_id="admin",
                        role="admin",
                        created_at=now,
                        updated_at=now,
                        created_by="system",
                        updated_by="system",
                    ))
            self._initialized = True

    async def list_users(self) -> list[StudioUserRecord]:
        await self._ensure_schema()
        async with self.engine.connect() as conn:
            rows = (await conn.execute(
                select(studio_users).order_by(studio_users.c.user_id.asc())
            )).all()
        return [self._row_to_record(row) for row in rows]

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
        filters = []
        if clean_query:
            filters.append(studio_users.c.user_id.ilike(f"%{clean_query}%"))
        if clean_role:
            filters.append(studio_users.c.role == clean_role)
        where_clause = and_(*filters) if filters else None

        count_stmt = select(func.count()).select_from(studio_users)
        list_stmt = select(studio_users).order_by(studio_users.c.user_id.asc())
        if where_clause is not None:
            count_stmt = count_stmt.where(where_clause)
            list_stmt = list_stmt.where(where_clause)
        list_stmt = list_stmt.limit(clean_limit).offset(clean_offset)

        async with self.engine.connect() as conn:
            total = (await conn.execute(count_stmt)).scalar_one()
            admin_count = (await conn.execute(
                select(func.count())
                .select_from(studio_users)
                .where(studio_users.c.role == "admin")
            )).scalar_one()
            rows = (await conn.execute(list_stmt)).all()
        return StudioUserPage(
            users=[self._row_to_record(row) for row in rows],
            total=total,
            admin_count=admin_count,
            limit=clean_limit,
            offset=clean_offset,
        )

    async def get_user(self, user_id: str) -> StudioUserRecord | None:
        await self._ensure_schema()
        async with self.engine.connect() as conn:
            row = (await conn.execute(
                select(studio_users).where(studio_users.c.user_id == user_id)
            )).first()
        return self._row_to_record(row) if row else None

    async def ensure_user(
        self, user_id: str, *, default_role: StudioRole = "viewer",
    ) -> StudioUserRecord:
        await self._ensure_schema()
        role = _validate_role(default_role)
        now = _utcnow()
        async with self.engine.begin() as conn:
            row = (await conn.execute(
                select(studio_users).where(studio_users.c.user_id == user_id)
            )).first()
            if row:
                return self._row_to_record(row)
            try:
                await conn.execute(insert(studio_users).values(
                    user_id=user_id,
                    role=role,
                    created_at=now,
                    updated_at=now,
                    created_by="login",
                    updated_by="login",
                ))
            except IntegrityError:
                row = (await conn.execute(
                    select(studio_users).where(studio_users.c.user_id == user_id)
                )).first()
                if row:
                    return self._row_to_record(row)
                raise
            row = (await conn.execute(
                select(studio_users).where(studio_users.c.user_id == user_id)
            )).one()
            return self._row_to_record(row)

    async def upsert_user(
        self, user_id: str, role: str, *, actor_user_id: str,
    ) -> StudioUserRecord:
        await self._ensure_schema()
        clean_role = _validate_role(role)
        now = _utcnow()
        async with self.engine.begin() as conn:
            row = (await conn.execute(
                select(studio_users).where(studio_users.c.user_id == user_id)
            )).first()
            if row:
                current = self._row_to_record(row)
                if current.role == "admin" and clean_role != "admin":
                    await self._assert_not_last_admin(conn)
                await conn.execute(
                    update(studio_users)
                    .where(studio_users.c.user_id == user_id)
                    .values(
                        role=clean_role,
                        updated_at=now,
                        updated_by=actor_user_id,
                    )
                )
            else:
                await conn.execute(insert(studio_users).values(
                    user_id=user_id,
                    role=clean_role,
                    created_at=now,
                    updated_at=now,
                    created_by=actor_user_id,
                    updated_by=actor_user_id,
                ))
            next_row = (await conn.execute(
                select(studio_users).where(studio_users.c.user_id == user_id)
            )).one()
            return self._row_to_record(next_row)

    async def delete_user(self, user_id: str) -> None:
        await self._ensure_schema()
        async with self.engine.begin() as conn:
            row = (await conn.execute(
                select(studio_users).where(studio_users.c.user_id == user_id)
            )).first()
            if not row:
                raise StudioUserNotFoundError(f"User grant not found: {user_id}")
            current = self._row_to_record(row)
            if current.role == "admin":
                await self._assert_not_last_admin(conn)
            await conn.execute(
                studio_users.delete().where(studio_users.c.user_id == user_id)
            )

    async def _assert_not_last_admin(self, conn) -> None:
        admin_count = (await conn.execute(
            select(func.count())
            .select_from(studio_users)
            .where(studio_users.c.role == "admin")
        )).scalar_one()
        if admin_count <= 1:
            raise LastAdminError("At least one admin is required")


def _database_url_from_env() -> str:
    return os.getenv("STUDIO_DATABASE_URL", DEFAULT_DATABASE_URL)


def _resolve_engine_for_singleton() -> AsyncEngine:
    """Pick the engine for the module-level singleton.

    Priority:
      1. ``STUDIO_DATABASE_URL`` set explicitly → legacy path, build a
         dedicated engine pointed at that URL (back-compat for deployments
         that already have ``data/ark_studio.db``).
      2. ``DB_TYPE=sqlite`` → reuse the central ``core.db`` engine so
         ``studio_users`` lives in the unified ``data/ark.db`` alongside
         business tables.
      3. Else → fall back to the default Studio URL (file mode legacy).
    """
    explicit_url = os.getenv("STUDIO_DATABASE_URL")
    if explicit_url:
        return _create_engine(explicit_url)

    db_type = os.environ.get("DB_TYPE", "file").strip().lower()
    if db_type == "sqlite":
        from ...core.db.engine import get_async_engine

        return get_async_engine()

    return _create_engine(DEFAULT_DATABASE_URL)


_store: StudioUserStore | None = None


def get_studio_user_store() -> StudioUserStore:
    """Module-level singleton accessor.

    Eagerly initialized in ``app.lifespan`` (Task 18) to prevent concurrent
    first-request races that could otherwise create duplicate AsyncEngine
    instances.
    """
    global _store
    if _store is None:
        _store = StudioUserStore(_resolve_engine_for_singleton())
    return _store


def reset_studio_user_store_cache() -> None:
    global _store
    _store = None


_GENERATED_TOKEN_SECRET = secrets.token_urlsafe(32)
_warned_generated_secret = False


def _token_secret() -> str:
    global _warned_generated_secret
    secret = os.getenv("STUDIO_AUTH_TOKEN_SECRET")
    if secret:
        return secret
    if not _warned_generated_secret:
        logger.warning(
            "STUDIO_AUTH_TOKEN_SECRET is not set; using a process-local generated secret"
        )
        _warned_generated_secret = True
    return _GENERATED_TOKEN_SECRET


def _token_ttl_seconds() -> int:
    raw = os.getenv("STUDIO_AUTH_TOKEN_TTL_SECONDS", str(DEFAULT_TOKEN_TTL_SECONDS))
    try:
        ttl = int(raw)
    except ValueError:
        logger.warning("Invalid STUDIO_AUTH_TOKEN_TTL_SECONDS=%r, using default", raw)
        return DEFAULT_TOKEN_TTL_SECONDS
    return max(ttl, 60)


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode((data + padding).encode("ascii"))


def issue_studio_token(user_id: str) -> str:
    now = int(time.time())
    payload = {
        "sub": user_id,
        "iat": now,
        "exp": now + _token_ttl_seconds(),
    }
    header = {"alg": "HS256", "typ": "JWT"}
    signing_input = ".".join((
        _b64encode(json.dumps(header, separators=(",", ":")).encode("utf-8")),
        _b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8")),
    ))
    signature = hmac.new(
        _token_secret().encode("utf-8"),
        signing_input.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return f"{signing_input}.{_b64encode(signature)}"


def issue_studio_token_id(user_id: str) -> str:
    return hashlib.sha256(user_id.encode("utf-8")).hexdigest()


def _decode_studio_token(token: str) -> dict:
    try:
        header_b64, payload_b64, signature_b64 = token.split(".", 2)
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid Studio token")
    signing_input = f"{header_b64}.{payload_b64}"
    expected = hmac.new(
        _token_secret().encode("utf-8"),
        signing_input.encode("ascii"),
        hashlib.sha256,
    ).digest()
    try:
        actual = _b64decode(signature_b64)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid Studio token")
    if not hmac.compare_digest(expected, actual):
        raise HTTPException(status_code=401, detail="Invalid Studio token")
    try:
        payload = json.loads(_b64decode(payload_b64))
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid Studio token")
    if int(payload.get("exp", 0)) < int(time.time()):
        raise HTTPException(status_code=401, detail="Studio token expired")
    if not payload.get("sub"):
        raise HTTPException(status_code=401, detail="Invalid Studio token")
    return payload


def _extract_bearer(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Studio token")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="Missing Studio token")
    return token


async def require_studio_user(
    authorization: str | None = Header(None, alias="Authorization"),
) -> StudioPrincipal:
    payload = _decode_studio_token(_extract_bearer(authorization))
    record = await get_studio_user_store().get_user(str(payload["sub"]))
    if record is None:
        raise HTTPException(status_code=403, detail="Studio user is not authorized")
    return StudioPrincipal(user_id=record.user_id, role=record.role)


def require_studio_roles(*allowed_roles: StudioRole):
    allowed = set(allowed_roles)

    async def _dependency(
        principal: StudioPrincipal = Depends(require_studio_user),
    ) -> StudioPrincipal:
        if principal.role not in allowed:
            raise HTTPException(status_code=403, detail="Insufficient Studio role")
        return principal

    return _dependency
