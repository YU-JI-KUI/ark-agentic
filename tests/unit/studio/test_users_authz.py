from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ark_agentic.studio.api import users as users_api
from ark_agentic.studio.services.authz_service import (
    get_studio_user_store,
)


@pytest.fixture
def client(studio_auth_context) -> TestClient:
    studio_auth_context()
    app = FastAPI()
    app.include_router(users_api.router, prefix="/api/studio")
    yield TestClient(app)


def test_users_require_token(client: TestClient) -> None:
    response = client.get("/api/studio/users")
    assert response.status_code == 401


def test_admin_can_upsert_list_and_delete_user_grant(client: TestClient, studio_auth_headers) -> None:
    created = client.post(
        "/api/studio/users",
        json={"user_id": "alice", "role": "editor"},
        headers=studio_auth_headers(),
    )
    assert created.status_code == 200
    assert created.json()["role"] == "editor"

    listed = client.get("/api/studio/users", headers=studio_auth_headers())
    assert listed.status_code == 200
    assert any(item["user_id"] == "alice" for item in listed.json()["users"])
    assert listed.json()["total"] >= 2
    assert listed.json()["admin_count"] == 1

    deleted = client.delete("/api/studio/users/alice", headers=studio_auth_headers())
    assert deleted.status_code == 200


def test_viewer_cannot_manage_users(client: TestClient, studio_auth_headers) -> None:
    get_studio_user_store().ensure_user("viewer-user", default_role="viewer")
    response = client.get("/api/studio/users", headers=studio_auth_headers("viewer-user"))
    assert response.status_code == 403


def test_admin_cannot_edit_self_even_when_other_admin_exists(
    client: TestClient, studio_auth_headers,
) -> None:
    get_studio_user_store().upsert_user("backup-admin", "admin", actor_user_id="admin")

    response = client.post(
        "/api/studio/users",
        json={"user_id": "admin", "role": "editor"},
        headers=studio_auth_headers(),
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Admins cannot edit their own user grant"
    assert get_studio_user_store().get_user("admin").role == "admin"


def test_admin_cannot_delete_self_even_when_other_admin_exists(
    client: TestClient, studio_auth_headers,
) -> None:
    get_studio_user_store().upsert_user("backup-admin", "admin", actor_user_id="admin")

    response = client.delete("/api/studio/users/admin", headers=studio_auth_headers())

    assert response.status_code == 403
    assert response.json()["detail"] == "Admins cannot delete their own user grant"
    assert get_studio_user_store().get_user("admin") is not None


def test_users_list_supports_pagination_and_filters(client: TestClient, studio_auth_headers) -> None:
    store = get_studio_user_store()
    store.upsert_user("alice", "viewer", actor_user_id="admin")
    store.upsert_user("alina", "editor", actor_user_id="admin")
    store.upsert_user("bob", "viewer", actor_user_id="admin")

    page = client.get(
        "/api/studio/users",
        params={"limit": 2, "offset": 1},
        headers=studio_auth_headers(),
    )
    assert page.status_code == 200
    body = page.json()
    assert body["limit"] == 2
    assert body["offset"] == 1
    assert body["total"] == 4
    assert len(body["users"]) == 2

    filtered = client.get(
        "/api/studio/users",
        params={"query": "ali", "role": "editor"},
        headers=studio_auth_headers(),
    )
    assert filtered.status_code == 200
    filtered_body = filtered.json()
    assert filtered_body["total"] == 1
    assert filtered_body["users"][0]["user_id"] == "alina"
