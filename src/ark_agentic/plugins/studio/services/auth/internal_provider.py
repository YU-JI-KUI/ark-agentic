"""Internal Studio authentication provider."""

from __future__ import annotations

import json
import logging
import os
from typing import Any, ClassVar

import bcrypt
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ark_agentic.plugins.studio.services.auth.provider import AuthCredentials, AuthProvider, StudioUser

logger = logging.getLogger(__name__)


class InternalAuthProvider(AuthProvider):
    """Authenticate against bcrypt users configured in ``STUDIO_USERS``."""

    name: ClassVar[str] = "internal"

    class UserEntry(BaseModel):
        """Loaded from JSON; credentials validated separately."""

        model_config = ConfigDict(extra="ignore")

        user_id: str
        display_name: str
        password_hash: str = Field(..., min_length=1)

    # Dev defaults: bcrypt hashes (admin: ark0606!, viewer: viewer123).
    DEFAULT_USERS: ClassVar[dict[str, dict[str, str]]] = {
        "admin": {
            "password_hash": "$2b$12$iC8oAqPzeSpBuRhWxQFEJe3aHABwF9gY/wmJjCcRuLcQq8KqTk8im",
            "user_id": "admin",
            "role": "editor",
            "display_name": "Admin",
        },
        "viewer": {
            "password_hash": "$2b$12$MqEJhgay.FbP/ip9HUgBjuTg55.6PdvJPmZs6N1VTnSy4lJVNPv/i",
            "user_id": "viewer",
            "role": "viewer",
            "display_name": "Viewer",
        },
    }

    async def authenticate(self, credentials: AuthCredentials) -> StudioUser | None:
        users = self._load_users()
        raw = users.get(credentials.username)
        if not raw or not isinstance(raw, dict):
            return None

        try:
            entry = self.UserEntry.model_validate(raw)
        except ValidationError:
            logger.warning("Invalid studio user record shape for username=%s", credentials.username)
            return None

        if not self._password_ok(entry, credentials.password):
            return None

        return StudioUser(
            user_id=entry.user_id,
            display_name=entry.display_name,
        )

    async def logout(self, *_args: Any, **_kwargs: Any) -> bool | None:
        return None

    def _load_users(self) -> dict[str, dict]:
        raw = os.getenv("STUDIO_USERS", "")
        if raw.strip():
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("STUDIO_USERS env is invalid JSON, falling back to defaults")
                return self.DEFAULT_USERS
            if not isinstance(data, dict):
                logger.warning("STUDIO_USERS must be a JSON object, falling back to defaults")
                return self.DEFAULT_USERS
            return data
        return self.DEFAULT_USERS

    def _password_ok(self, entry: InternalAuthProvider.UserEntry, plain: str) -> bool:
        try:
            return bcrypt.checkpw(
                plain.encode("utf-8"),
                entry.password_hash.encode("utf-8"),
            )
        except ValueError as e:
            logger.warning("Invalid bcrypt password_hash for user_id=%s: %s", entry.user_id, e)
            return False
