"""
Tests for studio/api/agents.py — Agent CRUD API

Uses a temp directory to simulate the agents/ filesystem.
Covers: list agents, get agent, create agent, and error cases.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ark_agentic.plugins.studio.api import agents as agents_api
from ark_agentic.plugins.studio.api.agents import AgentMeta, _read_agent_meta, _write_agent_meta
from ark_agentic.plugins.studio.services.auth import get_studio_user_repo


# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def temp_agents_dir(tmp_path: Path) -> Path:
    """Create a temporary agents root directory with sample agents."""
    agents_root = tmp_path / "agents"
    agents_root.mkdir()

    # Create agent with agent.json
    ins_dir = agents_root / "insurance"
    ins_dir.mkdir()
    (ins_dir / "agent.json").write_text(json.dumps({
        "id": "insurance",
        "name": "保险理赔助手",
        "description": "处理车险理赔",
        "status": "active",
    }), encoding="utf-8")
    (ins_dir / "skills").mkdir()
    (ins_dir / "tools").mkdir()

    # Create agent directory without agent.json (should auto-generate minimal meta)
    bare_dir = agents_root / "bare-agent"
    bare_dir.mkdir()

    # Create directory starting with "_" (should be skipped)
    hidden = agents_root / "_internal"
    hidden.mkdir()

    return agents_root


@pytest.fixture
def client(temp_agents_dir: Path, studio_auth_context) -> TestClient:
    """Create a FastAPI TestClient with the studio agents router
    and a patched get_agents_root pointing to the temp directory."""
    app = FastAPI()
    app.include_router(agents_api.router, prefix="/api/studio")

    with patch("ark_agentic.plugins.studio.api.agents.get_agents_root", return_value=temp_agents_dir):
        test_client = TestClient(app)
        studio_auth_context(client=test_client, database_dir=temp_agents_dir.parent)
        yield test_client


# ── Helper function tests ─────────────────────────────────────────────

class TestReadWriteAgentMeta:
    """Unit tests for _read_agent_meta and _write_agent_meta."""

    def test_read_existing_agent_json(self, temp_agents_dir: Path):
        """P0: Read a valid agent.json."""
        meta = _read_agent_meta(temp_agents_dir / "insurance")
        assert meta is not None
        assert meta.id == "insurance"
        assert meta.name == "保险理赔助手"

    def test_read_missing_agent_json(self, temp_agents_dir: Path):
        """P0: Return None if agent.json doesn't exist."""
        meta = _read_agent_meta(temp_agents_dir / "bare-agent")
        assert meta is None

    def test_read_invalid_json(self, temp_agents_dir: Path):
        """P2: Return None if agent.json is corrupted."""
        bad_dir = temp_agents_dir / "corrupted"
        bad_dir.mkdir()
        (bad_dir / "agent.json").write_text("{invalid json", encoding="utf-8")
        meta = _read_agent_meta(bad_dir)
        assert meta is None

    def test_write_then_read(self, tmp_path: Path):
        """P0: Write agent.json then read it back."""
        agent_dir = tmp_path / "test-agent"
        agent_dir.mkdir()

        original = AgentMeta(
            id="test-agent",
            name="测试助手",
            description="测试用",
            status="active",
        )
        _write_agent_meta(agent_dir, original)

        loaded = _read_agent_meta(agent_dir)
        assert loaded is not None
        assert loaded.id == original.id
        assert loaded.name == original.name
        assert loaded.description == original.description


# ── API endpoint tests ────────────────────────────────────────────────

class TestListAgentsEndpoint:
    """P0: GET /api/studio/agents"""

    def test_list_agents_returns_all(self, client: TestClient, temp_agents_dir: Path):
        """Should list all agents (with and without agent.json), skip hidden dirs."""
        with patch("ark_agentic.plugins.studio.api.agents.get_agents_root", return_value=temp_agents_dir):
            response = client.get("/api/studio/agents")
        assert response.status_code == 200
        data = response.json()
        agent_ids = [a["id"] for a in data["agents"]]
        assert "insurance" in agent_ids, f"Expected 'insurance' in {agent_ids}"
        assert "bare-agent" in agent_ids, f"Expected 'bare-agent' in {agent_ids}"
        assert "_internal" not in agent_ids, "Dirs starting with '_' should be skipped"

    def test_list_agents_insurance_has_name(self, client: TestClient, temp_agents_dir: Path):
        """Insurance agent should have the full name from agent.json."""
        with patch("ark_agentic.plugins.studio.api.agents.get_agents_root", return_value=temp_agents_dir):
            response = client.get("/api/studio/agents")
        agents = {a["id"]: a for a in response.json()["agents"]}
        assert agents["insurance"]["name"] == "保险理赔助手"

    def test_list_agents_bare_gets_fallback_name(self, client: TestClient, temp_agents_dir: Path):
        """Agent without agent.json should get its directory name as fallback."""
        with patch("ark_agentic.plugins.studio.api.agents.get_agents_root", return_value=temp_agents_dir):
            response = client.get("/api/studio/agents")
        agents = {a["id"]: a for a in response.json()["agents"]}
        assert agents["bare-agent"]["name"] == "bare-agent"


class TestGetAgentEndpoint:
    """P0: GET /api/studio/agents/{agent_id}"""

    def test_get_existing_agent(self, client: TestClient, temp_agents_dir: Path):
        """Should return the agent metadata."""
        with patch("ark_agentic.plugins.studio.api.agents.get_agents_root", return_value=temp_agents_dir):
            response = client.get("/api/studio/agents/insurance")
        assert response.status_code == 200
        assert response.json()["name"] == "保险理赔助手"

    def test_get_nonexistent_agent_returns_404(self, client: TestClient, temp_agents_dir: Path):
        """Should return 404 for missing agent."""
        with patch("ark_agentic.plugins.studio.api.agents.get_agents_root", return_value=temp_agents_dir):
            response = client.get("/api/studio/agents/nonexistent")
        assert response.status_code == 404

    def test_get_bare_agent_returns_fallback(self, client: TestClient, temp_agents_dir: Path):
        """Agent without agent.json should return fallback meta."""
        with patch("ark_agentic.plugins.studio.api.agents.get_agents_root", return_value=temp_agents_dir):
            response = client.get("/api/studio/agents/bare-agent")
        assert response.status_code == 200
        assert response.json()["id"] == "bare-agent"


class TestCreateAgentEndpoint:
    """P0: POST /api/studio/agents"""

    def test_create_new_agent(self, client: TestClient, temp_agents_dir: Path):
        """Should create directory, agent.json, skills/ and tools/ subdirs."""
        with patch("ark_agentic.plugins.studio.api.agents.get_agents_root", return_value=temp_agents_dir):
            response = client.post("/api/studio/agents", json={
                "id": "new-agent",
                "name": "新助手",
                "description": "Test agent",
            })
        assert response.status_code == 201, f"Expected 201, got {response.status_code}: {response.json()}"
        data = response.json()
        assert data["id"] == "new-agent"
        assert data["name"] == "新助手"
        assert data["status"] == "active"
        assert data["created_at"] != ""

        # Verify file system
        agent_dir = temp_agents_dir / "new-agent"
        assert agent_dir.is_dir()
        assert (agent_dir / "agent.json").is_file()
        assert (agent_dir / "skills").is_dir()
        assert (agent_dir / "tools").is_dir()

    def test_create_duplicate_agent_returns_409(self, client: TestClient, temp_agents_dir: Path):
        """Should return 409 if agent already exists."""
        with patch("ark_agentic.plugins.studio.api.agents.get_agents_root", return_value=temp_agents_dir):
            response = client.post("/api/studio/agents", json={
                "id": "insurance",
                "name": "Duplicate",
            })
        assert response.status_code == 409

    def test_create_agent_missing_required_field(self, client: TestClient, temp_agents_dir: Path):
        """Should return 422 if required 'id' or 'name' is missing."""
        with patch("ark_agentic.plugins.studio.api.agents.get_agents_root", return_value=temp_agents_dir):
            response = client.post("/api/studio/agents", json={
                "description": "No id or name",
            })
        assert response.status_code == 422

    async def test_create_agent_editor_allowed(
        self, client: TestClient, temp_agents_dir: Path, studio_auth_headers,
    ):
        """Editor role may use Studio write endpoints."""
        await get_studio_user_repo().upsert_user("ed", "editor", actor_user_id="admin")
        response = client.post(
            "/api/studio/agents",
            json={"id": "editor-agent", "name": "Editor Agent"},
            headers=studio_auth_headers("ed"),
        )
        assert response.status_code == 201

    async def test_create_agent_viewer_forbidden(
        self, client: TestClient, temp_agents_dir: Path, studio_auth_headers,
    ):
        """Viewer role cannot use Studio write endpoints."""
        await get_studio_user_repo().ensure_user("view-only", default_role="viewer")
        response = client.post(
            "/api/studio/agents",
            json={"id": "viewer-agent", "name": "Viewer Agent"},
            headers=studio_auth_headers("view-only"),
        )
        assert response.status_code == 403
