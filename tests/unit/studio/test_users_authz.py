from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ark_agentic.studio.api import users as users_api
from ark_agentic.studio.services.authz_service import (
    get_studio_user_store,
    issue_studio_token,
    reset_studio_user_store_cache,
)


@pytest.fixture
def client(tmp_path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("STUDIO_DATABASE_URL", f"sqlite:///{tmp_path}/ark_studio.db")
    monkeypatch.setenv("STUDIO_AUTH_TOKEN_SECRET", "test-secret")
    reset_studio_user_store_cache()
    app = FastAPI()
    app.include_router(users_api.router, prefix="/api/studio")
    try:
        yield TestClient(app)
    finally:
        reset_studio_user_store_cache()


def _headers(user_id: str = "admin") -> dict[str, str]:
    return {"Authorization": f"Bearer {issue_studio_token(user_id)}"}


def test_users_require_token(client: TestClient) -> None:
    response = client.get("/api/studio/users")
    assert response.status_code == 401


def test_admin_can_upsert_list_and_delete_user_grant(client: TestClient) -> None:
    created = client.post(
        "/api/studio/users",
        json={"user_id": "alice", "role": "editor"},
        headers=_headers(),
    )
    assert created.status_code == 200
    assert created.json()["role"] == "editor"

    listed = client.get("/api/studio/users", headers=_headers())
    assert listed.status_code == 200
    assert any(item["user_id"] == "alice" for item in listed.json()["users"])
    assert listed.json()["total"] >= 2
    assert listed.json()["admin_count"] == 1

    deleted = client.delete("/api/studio/users/alice", headers=_headers())
    assert deleted.status_code == 200


def test_viewer_cannot_manage_users(client: TestClient) -> None:
    get_studio_user_store().ensure_user("viewer-user", default_role="viewer")
    response = client.get("/api/studio/users", headers=_headers("viewer-user"))
    assert response.status_code == 403


def test_admin_cannot_edit_self_even_when_other_admin_exists(client: TestClient) -> None:
    get_studio_user_store().upsert_user("backup-admin", "admin", actor_user_id="admin")

    response = client.post(
        "/api/studio/users",
        json={"user_id": "admin", "role": "editor"},
        headers=_headers(),
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Admins cannot edit their own user grant"
    assert get_studio_user_store().get_user("admin").role == "admin"


def test_admin_cannot_delete_self_even_when_other_admin_exists(client: TestClient) -> None:
    get_studio_user_store().upsert_user("backup-admin", "admin", actor_user_id="admin")

    response = client.delete("/api/studio/users/admin", headers=_headers())

    assert response.status_code == 403
    assert response.json()["detail"] == "Admins cannot delete their own user grant"
    assert get_studio_user_store().get_user("admin") is not None


def test_users_list_supports_pagination_and_filters(client: TestClient) -> None:
    store = get_studio_user_store()
    store.upsert_user("alice", "viewer", actor_user_id="admin")
    store.upsert_user("alina", "editor", actor_user_id="admin")
    store.upsert_user("bob", "viewer", actor_user_id="admin")

    page = client.get(
        "/api/studio/users",
        params={"limit": 2, "offset": 1},
        headers=_headers(),
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
        headers=_headers(),
    )
    assert filtered.status_code == 200
    filtered_body = filtered.json()
    assert filtered_body["total"] == 1
    assert filtered_body["users"][0]["user_id"] == "alina"
