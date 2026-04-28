"""Tests for studio/api/auth.py — bcrypt login."""

from __future__ import annotations

import json

import bcrypt
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from ark_agentic.studio.api import auth as auth_api
from ark_agentic.studio.services.authz_service import get_studio_user_store, reset_studio_user_store_cache


@pytest.fixture
def auth_app() -> FastAPI:
    app = FastAPI()
    app.include_router(auth_api.router, prefix="/api/studio")
    return app


@pytest.fixture(autouse=True)
def studio_auth_db(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("STUDIO_DATABASE_URL", f"sqlite:///{tmp_path}/ark_studio.db")
    monkeypatch.setenv("STUDIO_AUTH_TOKEN_SECRET", "test-secret")
    reset_studio_user_store_cache()
    yield
    reset_studio_user_store_cache()


@pytest.mark.asyncio
async def test_login_default_admin_ok(monkeypatch: pytest.MonkeyPatch, auth_app: FastAPI) -> None:
    monkeypatch.delenv("STUDIO_USERS", raising=False)
    transport = ASGITransport(app=auth_app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        r = await client.post(
            "/api/studio/auth/login",
            json={"username": "admin", "password": "ark0606!"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["user_id"] == "admin"
    assert body["role"] == "admin"
    assert body["token"]


@pytest.mark.asyncio
async def test_login_default_viewer_ok(monkeypatch: pytest.MonkeyPatch, auth_app: FastAPI) -> None:
    monkeypatch.delenv("STUDIO_USERS", raising=False)
    transport = ASGITransport(app=auth_app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        r = await client.post(
            "/api/studio/auth/login",
            json={"username": "viewer", "password": "viewer123"},
        )
    assert r.status_code == 200
    assert r.json()["role"] == "viewer"
    assert get_studio_user_store().get_user("viewer") is not None


@pytest.mark.asyncio
async def test_login_wrong_password(monkeypatch: pytest.MonkeyPatch, auth_app: FastAPI) -> None:
    monkeypatch.delenv("STUDIO_USERS", raising=False)
    transport = ASGITransport(app=auth_app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        r = await client.post(
            "/api/studio/auth/login",
            json={"username": "admin", "password": "nope"},
        )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_login_unknown_user(monkeypatch: pytest.MonkeyPatch, auth_app: FastAPI) -> None:
    monkeypatch.delenv("STUDIO_USERS", raising=False)
    transport = ASGITransport(app=auth_app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        r = await client.post(
            "/api/studio/auth/login",
            json={"username": "nobody", "password": "x"},
        )
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
    transport = ASGITransport(app=auth_app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        ok = await client.post(
            "/api/studio/auth/login",
            json={"username": "alice", "password": "custom-secret"},
        )
        bad = await client.post(
            "/api/studio/auth/login",
            json={"username": "alice", "password": "wrong"},
        )
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
    transport = ASGITransport(app=auth_app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        r = await client.post(
            "/api/studio/auth/login",
            json={"username": "bob", "password": "plain-pass"},
        )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_invalid_studio_users_json_falls_back_to_defaults(
    monkeypatch: pytest.MonkeyPatch, auth_app: FastAPI,
) -> None:
    monkeypatch.setenv("STUDIO_USERS", "{not json")
    transport = ASGITransport(app=auth_app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        r = await client.post(
            "/api/studio/auth/login",
            json={"username": "admin", "password": "ark0606!"},
        )
    assert r.status_code == 200
