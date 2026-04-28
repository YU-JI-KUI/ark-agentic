"""
Studio Auth API — lightweight credential validation for internal use.

No JWT / cookie sessions. Frontend stores validated user object in localStorage.

User entries use ``password_hash`` (bcrypt) only. Optional env ``STUDIO_USERS`` is JSON
mapping username -> record.

Generate ``password_hash`` without putting secrets in shell history::

    uv run --extra server python -c "import bcrypt,getpass;print(bcrypt.hashpw(getpass.getpass().encode(),bcrypt.gensalt(12)).decode())"
"""

from __future__ import annotations

import json
import logging
import os

import bcrypt
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ark_agentic.studio.services.authz_service import StudioRole, get_studio_user_store, issue_studio_token

logger = logging.getLogger(__name__)

router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    user_id: str
    role: StudioRole
    display_name: str
    token: str


class _UserEntry(BaseModel):
    """Loaded from JSON; credentials validated separately."""

    model_config = ConfigDict(extra="ignore")

    user_id: str
    display_name: str
    password_hash: str = Field(..., min_length=1)


# Dev defaults: bcrypt hashes (admin: ark0606!, viewer: viewer123).
_DEFAULT_USERS: dict[str, dict[str, str]] = {
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


def _load_users() -> dict[str, dict]:
    raw = os.getenv("STUDIO_USERS", "")
    if raw.strip():
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("STUDIO_USERS env is invalid JSON, falling back to defaults")
            return _DEFAULT_USERS
        if not isinstance(data, dict):
            logger.warning("STUDIO_USERS must be a JSON object, falling back to defaults")
            return _DEFAULT_USERS
        return data
    return _DEFAULT_USERS


def _password_ok(entry: _UserEntry, plain: str) -> bool:
    try:
        return bcrypt.checkpw(
            plain.encode("utf-8"),
            entry.password_hash.encode("utf-8"),
        )
    except ValueError as e:
        logger.warning("Invalid bcrypt password_hash for user_id=%s: %s", entry.user_id, e)
        return False


@router.post("/auth/login", response_model=LoginResponse)
async def login(req: LoginRequest):
    users = _load_users()
    raw = users.get(req.username)
    if not raw or not isinstance(raw, dict):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    try:
        entry = _UserEntry.model_validate(raw)
    except ValidationError:
        logger.warning("Invalid studio user record shape for username=%s", req.username)
        raise HTTPException(status_code=401, detail="Invalid username or password")

    if not _password_ok(entry, req.password):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    record = get_studio_user_store().ensure_user(entry.user_id, default_role="viewer")

    return LoginResponse(
        user_id=entry.user_id,
        role=record.role,
        display_name=entry.display_name,
        token=issue_studio_token(entry.user_id),
    )
