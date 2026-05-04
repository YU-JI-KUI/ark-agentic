"""StudioUserRepository Protocol — Studio role grants store.

Studio is the operations console; users / roles live in DB regardless of
``DB_TYPE``. The protocol is DB-agnostic so future PG migration is a
one-file swap.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol, runtime_checkable

StudioRole = Literal["admin", "editor", "viewer"]
VALID_STUDIO_ROLES: set[str] = {"admin", "editor", "viewer"}


# ── DTOs ──────────────────────────────────────────────────────────


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


# ── Errors ────────────────────────────────────────────────────────


class StudioAuthzError(Exception):
    """Base class for Studio authorization store errors."""


class InvalidStudioRoleError(StudioAuthzError):
    """Unsupported role requested."""


class LastAdminError(StudioAuthzError):
    """A change would remove the last admin."""


class StudioUserNotFoundError(StudioAuthzError):
    """Target user grant does not exist."""


# ── Protocol ──────────────────────────────────────────────────────


@runtime_checkable
class StudioUserRepository(Protocol):
    """Studio role grants store.

    All write methods enforce the "at least one admin must remain"
    invariant. Implementations should raise ``LastAdminError`` rather
    than silently completing the operation.
    """

    async def ensure_schema(self) -> None:
        """Idempotent schema bootstrap (table + seed admin row)."""
        ...

    async def list_users_page(
        self,
        *,
        query: str = "",
        role: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> StudioUserPage:
        ...

    async def get_user(self, user_id: str) -> StudioUserRecord | None:
        ...

    async def ensure_user(
        self, user_id: str, *, default_role: StudioRole = "viewer",
    ) -> StudioUserRecord:
        """Idempotent insert-or-fetch. Used at login to materialize a
        first-time visitor with the default role."""
        ...

    async def upsert_user(
        self, user_id: str, role: str, *, actor_user_id: str,
    ) -> StudioUserRecord:
        ...

    async def delete_user(self, user_id: str) -> None:
        ...
