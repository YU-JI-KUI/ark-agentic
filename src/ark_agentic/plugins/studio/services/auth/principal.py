"""StudioPrincipal + FastAPI auth dependencies.

``require_studio_user`` resolves the bearer token to a ``StudioPrincipal``
backed by the Studio user repository. ``require_studio_roles(*roles)``
narrows access to a specific role set.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException

from .protocol import StudioRole
from .repo_singleton import get_studio_user_repo
from .tokens import decode_studio_token, extract_bearer


@dataclass(frozen=True)
class StudioPrincipal:
    user_id: str
    role: StudioRole


async def require_studio_user(
    authorization: str | None = Header(None, alias="Authorization"),
) -> StudioPrincipal:
    payload = decode_studio_token(extract_bearer(authorization))
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
