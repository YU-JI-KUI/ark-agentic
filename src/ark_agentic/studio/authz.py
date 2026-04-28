"""Studio user authorization store and signed-token helpers."""

from __future__ import annotations

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
from functools import lru_cache
from pathlib import Path
from threading import RLock
from typing import Literal

from fastapi import Depends, Header, HTTPException
from sqlalchemy import Column, DateTime, MetaData, String, Table, and_, create_engine, func, insert, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

logger = logging.getLogger(__name__)

StudioRole = Literal["admin", "editor", "viewer"]
VALID_STUDIO_ROLES: set[str] = {"admin", "editor", "viewer"}
DEFAULT_DATABASE_URL = "sqlite:///data/ark_studio.db"
DEFAULT_TOKEN_TTL_SECONDS = 43_200


metadata = MetaData()

studio_users = Table(
    "studio_users",
    metadata,
    Column("user_id", String(255), primary_key=True),
    Column("role", String(32), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("created_by", String(255), nullable=True),
    Column("updated_by", String(255), nullable=True),
)


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


def _sqlite_path_from_url(database_url: str) -> Path | None:
    if database_url == "sqlite:///:memory:":
        return None
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        return None
    return Path(database_url[len(prefix):]).expanduser()


def _create_engine(database_url: str) -> Engine:
    sqlite_path = _sqlite_path_from_url(database_url)
    if sqlite_path is not None:
        sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        return create_engine(
            database_url,
            future=True,
            connect_args={"check_same_thread": False},
        )
    return create_engine(database_url, future=True)


class StudioUserStore:
    """SQLAlchemy Core store for Studio role grants."""

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self.engine = _create_engine(database_url)
        self._lock = RLock()
        metadata.create_all(self.engine)
        self._seed_admin()

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

    def _seed_admin(self) -> None:
        now = _utcnow()
        with self._lock, self.engine.begin() as conn:
            exists = conn.execute(
                select(studio_users.c.user_id).where(studio_users.c.user_id == "admin")
            ).first()
            if exists:
                return
            conn.execute(insert(studio_users).values(
                user_id="admin",
                role="admin",
                created_at=now,
                updated_at=now,
                created_by="system",
                updated_by="system",
            ))

    def list_users(self) -> list[StudioUserRecord]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(studio_users).order_by(studio_users.c.user_id.asc())
            ).all()
        return [self._row_to_record(row) for row in rows]

    def list_users_page(
        self,
        *,
        query: str = "",
        role: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> StudioUserPage:
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

        with self.engine.connect() as conn:
            total = conn.execute(count_stmt).scalar_one()
            admin_count = conn.execute(
                select(func.count()).select_from(studio_users).where(studio_users.c.role == "admin")
            ).scalar_one()
            rows = conn.execute(list_stmt).all()
        return StudioUserPage(
            users=[self._row_to_record(row) for row in rows],
            total=total,
            admin_count=admin_count,
            limit=clean_limit,
            offset=clean_offset,
        )

    def get_user(self, user_id: str) -> StudioUserRecord | None:
        with self.engine.connect() as conn:
            row = conn.execute(
                select(studio_users).where(studio_users.c.user_id == user_id)
            ).first()
        return self._row_to_record(row) if row else None

    def ensure_user(self, user_id: str, *, default_role: StudioRole = "viewer") -> StudioUserRecord:
        role = _validate_role(default_role)
        now = _utcnow()
        with self._lock, self.engine.begin() as conn:
            row = conn.execute(
                select(studio_users).where(studio_users.c.user_id == user_id)
            ).first()
            if row:
                return self._row_to_record(row)
            try:
                conn.execute(insert(studio_users).values(
                    user_id=user_id,
                    role=role,
                    created_at=now,
                    updated_at=now,
                    created_by="login",
                    updated_by="login",
                ))
            except IntegrityError:
                row = conn.execute(
                    select(studio_users).where(studio_users.c.user_id == user_id)
                ).first()
                if row:
                    return self._row_to_record(row)
                raise
            row = conn.execute(
                select(studio_users).where(studio_users.c.user_id == user_id)
            ).one()
            return self._row_to_record(row)

    def upsert_user(self, user_id: str, role: str, *, actor_user_id: str) -> StudioUserRecord:
        clean_role = _validate_role(role)
        now = _utcnow()
        with self._lock, self.engine.begin() as conn:
            row = conn.execute(
                select(studio_users).where(studio_users.c.user_id == user_id)
            ).first()
            if row:
                current = self._row_to_record(row)
                if current.role == "admin" and clean_role != "admin":
                    self._assert_not_last_admin(conn)
                conn.execute(
                    update(studio_users)
                    .where(studio_users.c.user_id == user_id)
                    .values(role=clean_role, updated_at=now, updated_by=actor_user_id)
                )
            else:
                conn.execute(insert(studio_users).values(
                    user_id=user_id,
                    role=clean_role,
                    created_at=now,
                    updated_at=now,
                    created_by=actor_user_id,
                    updated_by=actor_user_id,
                ))
            next_row = conn.execute(
                select(studio_users).where(studio_users.c.user_id == user_id)
            ).one()
            return self._row_to_record(next_row)

    def delete_user(self, user_id: str) -> None:
        with self._lock, self.engine.begin() as conn:
            row = conn.execute(
                select(studio_users).where(studio_users.c.user_id == user_id)
            ).first()
            if not row:
                raise StudioUserNotFoundError(f"User grant not found: {user_id}")
            current = self._row_to_record(row)
            if current.role == "admin":
                self._assert_not_last_admin(conn)
            conn.execute(studio_users.delete().where(studio_users.c.user_id == user_id))

    def _assert_not_last_admin(self, conn) -> None:
        admin_count = conn.execute(
            select(func.count()).select_from(studio_users).where(studio_users.c.role == "admin")
        ).scalar_one()
        if admin_count <= 1:
            raise LastAdminError("At least one admin is required")


def _database_url_from_env() -> str:
    return os.getenv("STUDIO_DATABASE_URL", DEFAULT_DATABASE_URL)


@lru_cache(maxsize=1)
def get_studio_user_store() -> StudioUserStore:
    return StudioUserStore(_database_url_from_env())


def reset_studio_user_store_cache() -> None:
    get_studio_user_store.cache_clear()


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
    record = get_studio_user_store().get_user(str(payload["sub"]))
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
