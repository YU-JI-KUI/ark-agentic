"""Tests for studio/api/auth.py — bcrypt login."""

from __future__ import annotations

import json
import logging

import bcrypt
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response

from ark_agentic.studio.api import auth as auth_api
from ark_agentic.studio.services import auth_service
from ark_agentic.studio.services.auth import AuthCredentials, AuthProvider, StudioUser
from ark_agentic.studio.services.authz_service import get_studio_user_store


@pytest.fixture
def auth_app() -> FastAPI:
    app = FastAPI()
    app.include_router(auth_api.router, prefix="/api/studio")
    return app


async def _post_login(
    app: FastAPI,
    *,
    username: str = "admin",
    password: str = "ark0606!",
    headers: dict[str, str] | None = None,
    client_address: tuple[str, int] = ("127.0.0.1", 123),
) -> Response:
    transport = ASGITransport(app=app, client=client_address)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        return await client.post(
            "/api/studio/auth/login",
            headers=headers,
            json={"username": username, "password": password},
        )


@pytest.fixture(autouse=True)
def studio_auth_db(studio_auth_context):
    studio_auth_context()


@pytest.mark.asyncio
async def test_login_default_admin_ok(monkeypatch: pytest.MonkeyPatch, auth_app: FastAPI) -> None:
    monkeypatch.delenv("STUDIO_USERS", raising=False)
    r = await _post_login(auth_app)
    assert r.status_code == 200
    body = r.json()
    assert body["user_id"] == "admin"
    assert body["role"] == "admin"
    assert body["token"]


@pytest.mark.asyncio
async def test_login_default_viewer_ok(monkeypatch: pytest.MonkeyPatch, auth_app: FastAPI) -> None:
    monkeypatch.delenv("STUDIO_USERS", raising=False)
    r = await _post_login(auth_app, username="viewer", password="viewer123")
    assert r.status_code == 200
    assert r.json()["role"] == "viewer"
    assert get_studio_user_store().get_user("viewer") is not None


@pytest.mark.asyncio
async def test_login_wrong_password(monkeypatch: pytest.MonkeyPatch, auth_app: FastAPI) -> None:
    monkeypatch.delenv("STUDIO_USERS", raising=False)
    r = await _post_login(auth_app, password="nope")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_login_unknown_user(monkeypatch: pytest.MonkeyPatch, auth_app: FastAPI) -> None:
    monkeypatch.delenv("STUDIO_USERS", raising=False)
    r = await _post_login(auth_app, username="nobody", password="x")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_studio_users_password_hash(monkeypatch: pytest.MonkeyPatch, auth_app: FastAPI) -> None:
    h = bcrypt.hashpw(b"custom-secret", bcrypt.gensalt(rounds=8)).decode()
    users = {
        "alice": {
            "password_hash": h,
            "user_id": "alice",
            "display_name": "Alice",
        }
    }
    monkeypatch.setenv("STUDIO_USERS", json.dumps(users))
    ok = await _post_login(auth_app, username="alice", password="custom-secret")
    bad = await _post_login(auth_app, username="alice", password="wrong")
    assert ok.status_code == 200
    assert ok.json()["role"] == "viewer"
    assert bad.status_code == 401


@pytest.mark.asyncio
async def test_plaintext_password_field_rejected(monkeypatch: pytest.MonkeyPatch, auth_app: FastAPI) -> None:
    """Entries with only legacy ``password`` (no password_hash) cannot validate."""
    users = {
        "bob": {
            "password": "plain-pass",
            "user_id": "bob",
            "role": "viewer",
            "display_name": "Bob",
        }
    }
    monkeypatch.setenv("STUDIO_USERS", json.dumps(users))
    r = await _post_login(auth_app, username="bob", password="plain-pass")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_invalid_studio_users_json_falls_back_to_defaults(
    monkeypatch: pytest.MonkeyPatch, auth_app: FastAPI,
) -> None:
    monkeypatch.setenv("STUDIO_USERS", "{not json")
    r = await _post_login(auth_app)
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_login_explicit_internal_provider_ok(
    monkeypatch: pytest.MonkeyPatch, auth_app: FastAPI,
) -> None:
    monkeypatch.setenv("STUDIO_AUTH_PROVIDERS", "internal")
    r = await _post_login(auth_app)
    assert r.status_code == 200
    assert r.json()["user_id"] == "admin"


@pytest.mark.asyncio
async def test_login_unknown_provider_is_warned_and_skipped(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    auth_app: FastAPI,
) -> None:
    monkeypatch.setenv("STUDIO_AUTH_PROVIDERS", "ldap,internal")
    caplog.set_level(logging.WARNING, logger=auth_service.__name__)

    r = await _post_login(auth_app)

    assert r.status_code == 200
    assert "Unknown Studio auth provider configured: ldap" in caplog.text


@pytest.mark.asyncio
async def test_login_unknown_provider_without_internal_fails(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    auth_app: FastAPI,
) -> None:
    monkeypatch.setenv("STUDIO_AUTH_PROVIDERS", "ldap")
    caplog.set_level(logging.WARNING, logger=auth_service.__name__)

    r = await _post_login(auth_app)

    assert r.status_code == 401
    assert "Unknown Studio auth provider configured: ldap" in caplog.text


@pytest.mark.asyncio
async def test_login_provider_chain_stops_after_success(
    monkeypatch: pytest.MonkeyPatch,
    auth_app: FastAPI,
) -> None:
    calls: list[str] = []

    class FailProvider(AuthProvider):
        name = "fail"

        async def authenticate(
            self, credentials: AuthCredentials,
        ) -> StudioUser | None:
            calls.append(self.name)
            return None

    class SuccessProvider(AuthProvider):
        name = "success"

        async def authenticate(
            self, credentials: AuthCredentials,
        ) -> StudioUser | None:
            calls.append(self.name)
            return StudioUser(
                user_id="chain-user",
                display_name="Chain User",
            )

    class LaterProvider(AuthProvider):
        name = "later"

        async def authenticate(
            self, credentials: AuthCredentials,
        ) -> StudioUser | None:
            calls.append(self.name)
            raise AssertionError("provider chain should stop after first success")

    monkeypatch.setitem(auth_service.AUTH_PROVIDER_CLASSES, "fail", FailProvider)
    monkeypatch.setitem(auth_service.AUTH_PROVIDER_CLASSES, "success", SuccessProvider)
    monkeypatch.setitem(auth_service.AUTH_PROVIDER_CLASSES, "later", LaterProvider)
    monkeypatch.setenv("STUDIO_AUTH_PROVIDERS", "fail,success,later")

    r = await _post_login(auth_app, username="any", password="secret")

    assert r.status_code == 200
    assert r.json()["user_id"] == "chain-user"
    assert r.json()["role"] == "viewer"
    assert calls == ["fail", "success"]


@pytest.mark.asyncio
async def test_login_passes_request_context_to_auth_provider(
    monkeypatch: pytest.MonkeyPatch,
    auth_app: FastAPI,
) -> None:
    seen: list[AuthCredentials] = []

    class ContextProvider(AuthProvider):
        name = "context"

        async def authenticate(self, credentials: AuthCredentials) -> StudioUser | None:
            seen.append(credentials)
            return StudioUser(user_id="context-user", display_name="Context User")

    monkeypatch.setitem(auth_service.AUTH_PROVIDER_CLASSES, "context", ContextProvider)
    monkeypatch.setenv("STUDIO_AUTH_PROVIDERS", "context")

    r = await _post_login(
        auth_app,
        username="any",
        password="secret",
        headers={"X-Studio-Auth-Context": "from-header"},
        client_address=("203.0.113.10", 1234),
    )

    assert r.status_code == 200
    assert len(seen) == 1
    assert seen[0].username == "any"
    assert seen[0].password == "secret"
    assert seen[0].client_ip == "203.0.113.10"
    assert seen[0].headers["x-studio-auth-context"] == "from-header"
