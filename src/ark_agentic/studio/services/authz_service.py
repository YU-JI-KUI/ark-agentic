"""Studio authorization — token helpers + thin facade over StudioUserRepository.

The storage logic has moved to ``core.storage.backends.sqlite.studio_user``
(``SqliteStudioUserRepository``) — this module now only owns:

- HMAC-signed token issue / decode
- FastAPI dependencies (``require_studio_user``, ``require_studio_roles``)
- The module-level singleton accessor (``get_studio_user_repo``)
- The DTO / error re-exports that downstream code historically imported
  from this module.

When ``DB_TYPE=sqlite`` Studio rides on the central ``core.db`` engine so
``studio_users`` lives in the same DB file as business tables. Otherwise a
dedicated SQLite engine is created against ``data/ark_studio.db``.
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
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ...core.db.base import Base
from ...core.db.models import StudioUser
from ...core.storage.backends.sqlite.studio_user import (
    SqliteStudioUserRepository,
    seed_default_admin,
)
from ...core.storage.protocols import (  # re-exported below
    InvalidStudioRoleError,
    LastAdminError,
    StudioAuthzError,
    StudioRole,
    StudioUserNotFoundError,
    StudioUserPage,
    StudioUserRecord,
    StudioUserRepository,
    VALID_STUDIO_ROLES,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

DEFAULT_STUDIO_DB_PATH = Path("data/ark_studio.db")
DEFAULT_TOKEN_TTL_SECONDS = 43_200

# Re-exports (downstream imports kept stable through one layer of indirection).
metadata = Base.metadata
studio_users = StudioUser.__table__

# Public re-exports for the principal / role types used in API decorators.
from dataclasses import dataclass


@dataclass(frozen=True)
class StudioPrincipal:
    user_id: str
    role: StudioRole


__all__ = [
    "StudioRole",
    "VALID_STUDIO_ROLES",
    "StudioUserRecord",
    "StudioUserPage",
    "StudioPrincipal",
    "StudioAuthzError",
    "InvalidStudioRoleError",
    "LastAdminError",
    "StudioUserNotFoundError",
    "issue_studio_token",
    "issue_studio_token_id",
    "require_studio_user",
    "require_studio_roles",
    "get_studio_user_repo",
    "ensure_studio_schema",
    "reset_studio_user_repo_cache",
    "metadata",
    "studio_users",
]


# ── Engine selection ──────────────────────────────────────────────


def _resolve_studio_engine() -> AsyncEngine:
    """Pick the AsyncEngine for the Studio repository singleton.

    Order:
      1. ``STUDIO_DATABASE_URL`` set → dedicated engine (test override /
         deployments that intentionally split Studio off the main DB).
      2. ``DB_TYPE=sqlite`` → reuse the central engine so ``studio_users``
         sits next to business tables in one DB file.
      3. Otherwise → dedicated ``data/ark_studio.db`` engine.
    """
    explicit_url = os.environ.get("STUDIO_DATABASE_URL")
    if explicit_url:
        return _build_dedicated_engine(explicit_url)

    db_type = os.environ.get("DB_TYPE", "file").strip().lower()
    if db_type == "sqlite":
        from ...core.db.engine import get_async_engine

        return get_async_engine()

    return _build_dedicated_engine(
        f"sqlite+aiosqlite:///{DEFAULT_STUDIO_DB_PATH.as_posix()}",
    )


def _build_dedicated_engine(database_url: str) -> AsyncEngine:
    # Promote sync sqlite URLs to aiosqlite.
    if database_url.startswith("sqlite:///") and not database_url.startswith(
        "sqlite+aiosqlite:///"
    ):
        database_url = (
            "sqlite+aiosqlite:///" + database_url[len("sqlite:///"):]
        )
    # Ensure the parent dir exists when pointing at a real file.
    if database_url.startswith("sqlite+aiosqlite:///") and not database_url.endswith(
        ":memory:"
    ):
        Path(
            database_url[len("sqlite+aiosqlite:///"):]
        ).parent.mkdir(parents=True, exist_ok=True)
    return create_async_engine(
        database_url,
        future=True,
        connect_args={"check_same_thread": False},
    )


_repo: StudioUserRepository | None = None
_init_lock = asyncio.Lock()
_initialized = False


def get_studio_user_repo() -> StudioUserRepository:
    """Module-level singleton accessor.

    Lifespan calls ``ensure_studio_schema()`` at startup so the schema +
    bootstrap admin row are present before the first request.
    """
    global _repo
    if _repo is None:
        _repo = SqliteStudioUserRepository(_resolve_studio_engine())
    return _repo


async def ensure_studio_schema() -> None:
    """Create studio_users table (if needed) and seed the bootstrap admin.

    Safe to call repeatedly; double-checked-locking guards the seed insert.
    Lifespan calls this exactly once at startup.
    """
    global _initialized
    if _initialized:
        return
    async with _init_lock:
        if _initialized:
            return
        repo = get_studio_user_repo()
        engine: AsyncEngine = repo._engine  # type: ignore[attr-defined]
        async with engine.begin() as conn:
            await conn.run_sync(metadata.create_all)
        await seed_default_admin(repo)  # type: ignore[arg-type]
        _initialized = True


def reset_studio_user_repo_cache() -> None:
    """Test helper — drop the singleton + initialization marker."""
    global _repo, _initialized
    _repo = None
    _initialized = False


# ── Token helpers (unchanged) ─────────────────────────────────────


_GENERATED_TOKEN_SECRET = secrets.token_urlsafe(32)
_warned_generated_secret = False


def _token_secret() -> str:
    global _warned_generated_secret
    secret = os.getenv("STUDIO_AUTH_TOKEN_SECRET")
    if secret:
        return secret
    if not _warned_generated_secret:
        logger.warning(
            "STUDIO_AUTH_TOKEN_SECRET is not set; using a "
            "process-local generated secret"
        )
        _warned_generated_secret = True
    return _GENERATED_TOKEN_SECRET


def _token_ttl_seconds() -> int:
    raw = os.getenv(
        "STUDIO_AUTH_TOKEN_TTL_SECONDS", str(DEFAULT_TOKEN_TTL_SECONDS),
    )
    try:
        ttl = int(raw)
    except ValueError:
        logger.warning(
            "Invalid STUDIO_AUTH_TOKEN_TTL_SECONDS=%r, using default", raw,
        )
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


# ── FastAPI dependencies ──────────────────────────────────────────


async def require_studio_user(
    authorization: str | None = Header(None, alias="Authorization"),
) -> StudioPrincipal:
    payload = _decode_studio_token(_extract_bearer(authorization))
    record = await get_studio_user_repo().get_user(str(payload["sub"]))
    if record is None:
        raise HTTPException(
            status_code=403, detail="Studio user is not authorized",
        )
    return StudioPrincipal(user_id=record.user_id, role=record.role)


def require_studio_roles(*allowed_roles: StudioRole):
    allowed = set(allowed_roles)

    async def _dependency(
        principal: StudioPrincipal = Depends(require_studio_user),
    ) -> StudioPrincipal:
        if principal.role not in allowed:
            raise HTTPException(
                status_code=403, detail="Insufficient Studio role",
            )
        return principal

    return _dependency
