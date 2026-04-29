"""Studio authentication provider orchestration."""

from __future__ import annotations

import logging
import os

from ark_agentic.studio.services.auth import (
    AuthCredentials,
    AuthProvider,
    InternalAuthProvider,
    StudioUser,
)

logger = logging.getLogger(__name__)

DEFAULT_AUTH_PROVIDER_NAMES = ("internal",)

AUTH_PROVIDER_CLASSES: dict[str, type[AuthProvider]] = {
    InternalAuthProvider.name: InternalAuthProvider,
}


def _auth_provider_names_from_env() -> list[str]:
    raw = os.getenv("STUDIO_AUTH_PROVIDERS", "")
    if not raw.strip():
        return list(DEFAULT_AUTH_PROVIDER_NAMES)
    names = [name.strip().lower() for name in raw.split(",") if name.strip()]
    return names or list(DEFAULT_AUTH_PROVIDER_NAMES)


async def authenticate_studio_user(credentials: AuthCredentials) -> StudioUser | None:
    for provider_name in _auth_provider_names_from_env():
        provider_cls = AUTH_PROVIDER_CLASSES.get(provider_name)
        if provider_cls is None:
            logger.warning("Unknown Studio auth provider configured: %s", provider_name)
            continue

        studio_user = await provider_cls().authenticate(credentials)
        if studio_user is not None:
            return studio_user
    return None
