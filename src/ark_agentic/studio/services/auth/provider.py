"""Studio authentication provider interfaces."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar, Mapping

from ark_agentic.studio.services.authz_service import StudioRole


@dataclass(frozen=True)
class AuthCredentials:
    username: str
    password: str
    client_ip: str | None = None
    headers: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class StudioUser:
    user_id: str
    display_name: str
    default_role: StudioRole = "viewer"


class AuthProvider(ABC):
    """Credential provider interface for Studio login."""

    name: ClassVar[str]

    @abstractmethod
    async def authenticate(self, credentials: AuthCredentials) -> StudioUser | None:
        """Return an authenticated user, or None when credentials do not match."""

    async def logout(self, *_args: Any, **_kwargs: Any) -> bool | None:
        """Release provider-specific login state when applicable."""
        return None
