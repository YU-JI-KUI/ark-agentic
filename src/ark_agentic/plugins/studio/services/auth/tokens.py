"""Studio HMAC-signed bearer tokens (HS256).

Pure functions — no storage dependency. Used by login (issue) and the
``require_studio_user`` FastAPI dependency (decode).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time

from fastapi import HTTPException

logger = logging.getLogger(__name__)

DEFAULT_TOKEN_TTL_SECONDS = 43_200

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


def decode_studio_token(token: str) -> dict:
    """Verify the HMAC + expiry. Raises 401 ``HTTPException`` on failure."""
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


def extract_bearer(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Studio token")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="Missing Studio token")
    return token
