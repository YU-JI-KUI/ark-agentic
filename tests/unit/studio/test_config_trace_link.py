"""Tests for /api/studio/config/trace-link."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def config_app(monkeypatch) -> FastAPI:
    for var in (
        "STUDIO_TRACE_URL_TEMPLATE",
        "TRACING",
        "PHOENIX_COLLECTOR_ENDPOINT",
        "PHOENIX_PROJECT_NAME",
        "LANGFUSE_PUBLIC_KEY",
        "LANGFUSE_HOST",
    ):
        monkeypatch.delenv(var, raising=False)
    from ark_agentic.plugins.studio.api import config as config_api

    app = FastAPI()
    app.include_router(config_api.router, prefix="/api/studio")
    return app


@pytest.mark.asyncio
async def test_returns_disabled_when_no_provider(config_app: FastAPI) -> None:
    transport = ASGITransport(app=config_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/studio/config/trace-link")
    assert r.status_code == 200
    assert r.json() == {"enabled": False, "template": None}


@pytest.mark.asyncio
async def test_returns_template_when_phoenix_configured(
    config_app: FastAPI, monkeypatch
) -> None:
    monkeypatch.setenv("PHOENIX_COLLECTOR_ENDPOINT", "http://x:6006/v1/traces")
    transport = ASGITransport(app=config_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/studio/config/trace-link")
    body = r.json()
    assert body["enabled"] is True
    assert "{trace_id}" in body["template"]


@pytest.mark.asyncio
async def test_returns_explicit_override(
    config_app: FastAPI, monkeypatch
) -> None:
    monkeypatch.setenv(
        "STUDIO_TRACE_URL_TEMPLATE", "https://custom.example/t/{trace_id}"
    )
    transport = ASGITransport(app=config_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/studio/config/trace-link")
    assert r.json() == {
        "enabled": True,
        "template": "https://custom.example/t/{trace_id}",
    }
