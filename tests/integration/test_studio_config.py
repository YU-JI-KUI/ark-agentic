from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from ark_agentic.plugins.studio.api import config as config_api


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(config_api.router, prefix="/api/studio")
    return TestClient(app)


def test_studio_features_mcp_disabled_by_default(
    monkeypatch,
) -> None:
    monkeypatch.delenv("ENABLE_MCP", raising=False)

    response = _client().get("/api/studio/config/features")

    assert response.status_code == 200
    assert response.json() == {"mcp_enabled": False}


def test_studio_features_mcp_enabled(
    monkeypatch,
) -> None:
    monkeypatch.setenv("ENABLE_MCP", "true")

    response = _client().get("/api/studio/config/features")

    assert response.status_code == 200
    assert response.json() == {"mcp_enabled": True}
