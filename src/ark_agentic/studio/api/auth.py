"""
Studio Auth API — lightweight credential validation for internal use.

No JWT / cookie sessions. Frontend stores validated user object in localStorage.
"""

from __future__ import annotations

import hmac
import json
import logging
import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter()

# ── User model ───────────────────────────────────────────────────────

class StudioUser(BaseModel):
    user_id: str
    role: str          # "editor" | "viewer"
    display_name: str


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    user_id: str
    role: str
    display_name: str


# ── Default users (overridable via STUDIO_USERS env JSON) ────────────

_DEFAULT_USERS: dict[str, dict] = {
    "admin": {
        "password": "admin123",
        "user_id": "admin",
        "role": "editor",
        "display_name": "Admin",
    },
    "viewer": {
        "password": "viewer123",
        "user_id": "viewer",
        "role": "viewer",
        "display_name": "Viewer",
    },
}


def _load_users() -> dict[str, dict]:
    raw = os.getenv("STUDIO_USERS", "")
    if raw.strip():
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("STUDIO_USERS env is invalid JSON, falling back to defaults")
    return _DEFAULT_USERS


# ── Endpoint ─────────────────────────────────────────────────────────

@router.post("/auth/login", response_model=LoginResponse)
async def login(req: LoginRequest):
    users = _load_users()
    entry = users.get(req.username)
    if not entry or not hmac.compare_digest(entry["password"], req.password):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    return LoginResponse(
        user_id=entry["user_id"],
        role=entry["role"],
        display_name=entry["display_name"],
    )
