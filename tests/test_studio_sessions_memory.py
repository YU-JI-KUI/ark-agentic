"""
Studio Sessions & Memory API tests.

Tests use deps.init_registry() to inject a registry with a mock AgentRunner.
"""

import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI

from ark_agentic.api.deps import init_registry
from ark_agentic.studio.api.sessions import router as sessions_router
from ark_agentic.studio.api.memory import router as memory_router
from ark_agentic.core.registry import AgentRegistry


# ── Dummy objects ───────────────────────────────────────────────────

class DummyMessage:
    def __init__(self, role, content, tool_calls=None):
        self.role = role
        self.content = content
        self.tool_calls = tool_calls or []


class DummySession:
    def __init__(self, sid, msgs=None, state=None):
        self.session_id = sid
        self.messages = msgs or []
        self.state = state or {}


class DummySessionManager:
    def __init__(self, sessions=None):
        self._sessions = {s.session_id: s for s in (sessions or [])}

    def list_sessions(self):
        return list(self._sessions.values())

    def get_session(self, sid):
        return self._sessions.get(sid)

    def create_session_sync(self, state=None):
        sid = f"new-{len(self._sessions) + 1}"
        s = DummySession(sid, state=state or {})
        self._sessions[sid] = s
        return s

    def delete_session_sync(self, sid):
        return self._sessions.pop(sid, None) is not None


class DummyAgentRunner:
    def __init__(self, sessions=None):
        self.session_manager = DummySessionManager(sessions)


# ── Test setup ──────────────────────────────────────────────────────

app = FastAPI()
app.include_router(sessions_router, prefix="/api/studio")
app.include_router(memory_router, prefix="/api/studio")
client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_registry():
    """Inject a clean registry before each test."""
    registry = AgentRegistry()
    runner = DummyAgentRunner([
        DummySession("sid1", [DummyMessage("user", "hi"), DummyMessage("assistant", "hello")], {"foo": "bar"}),
        DummySession("sid2", [], {}),
    ])
    registry.register("insurance", runner)
    init_registry(registry)
    yield


# ── Session list tests ──────────────────────────────────────────────

def test_list_sessions_success():
    response = client.get("/api/studio/agents/insurance/sessions")
    assert response.status_code == 200
    data = response.json()
    assert len(data["sessions"]) == 2
    assert data["sessions"][0]["session_id"] == "sid1"
    assert data["sessions"][0]["message_count"] == 2
    assert data["sessions"][0]["state"] == {"foo": "bar"}


def test_list_sessions_agent_not_found():
    response = client.get("/api/studio/agents/missing/sessions")
    assert response.status_code == 200
    data = response.json()
    assert data["sessions"] == []


# ── Session create tests ────────────────────────────────────────────

def test_create_session():
    response = client.post(
        "/api/studio/agents/insurance/sessions",
        json={"state": {"user": "test"}},
    )
    assert response.status_code == 200
    data = response.json()
    assert "session_id" in data
    assert data["state"] == {"user": "test"}


def test_create_session_agent_not_found():
    response = client.post("/api/studio/agents/missing/sessions")
    assert response.status_code == 404


# ── Session detail tests ────────────────────────────────────────────

def test_get_session_detail():
    response = client.get("/api/studio/agents/insurance/sessions/sid1")
    assert response.status_code == 200
    data = response.json()
    assert data["session_id"] == "sid1"
    assert len(data["messages"]) == 2
    assert data["messages"][0]["role"] == "user"
    assert data["messages"][0]["content"] == "hi"


def test_get_session_detail_not_found():
    response = client.get("/api/studio/agents/insurance/sessions/nonexistent")
    assert response.status_code == 404


# ── Session delete tests ────────────────────────────────────────────

def test_delete_session():
    response = client.delete("/api/studio/agents/insurance/sessions/sid2")
    assert response.status_code == 200
    assert response.json()["status"] == "deleted"

    # Verify it's gone
    response = client.get("/api/studio/agents/insurance/sessions/sid2")
    assert response.status_code == 404


def test_delete_session_not_found():
    response = client.delete("/api/studio/agents/insurance/sessions/nonexistent")
    assert response.status_code == 404


# ── Memory tests (unchanged) ───────────────────────────────────────

def test_get_memory_not_implemented():
    response = client.get("/api/studio/agents/insurance/memory")
    assert response.status_code == 501
    assert "not yet implemented" in response.json()["detail"]
