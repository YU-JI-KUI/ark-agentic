import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI

from ark_agentic.studio.api.sessions import router as sessions_router, init as init_sessions
from ark_agentic.studio.api.memory import router as memory_router
from ark_agentic.core.registry import AgentRegistry

app = FastAPI()
app.include_router(sessions_router)
app.include_router(memory_router)
client = TestClient(app)

# Dummy AgentRunner and Session objects for testing
class DummySession:
    def __init__(self, sid, msgs, state):
        self.session_id = sid
        self.messages = msgs
        self.state = state

class DummySessionManager:
    def __init__(self, sessions):
        self._sessions = sessions
    def list_sessions(self):
        return self._sessions

class DummyAgentRunner:
    def __init__(self, sessions):
        self.session_manager = DummySessionManager(sessions)

def test_list_sessions_not_initialized():
    # Force _registry to None for checking 503
    import ark_agentic.studio.api.sessions as s
    s._registry = None
    response = client.get("/agents/a1/sessions")
    assert response.status_code == 503

def test_list_sessions_success():
    registry = AgentRegistry()
    runner = DummyAgentRunner([
        DummySession("sid1", [1, 2, 3], {"foo": "bar"}),
        DummySession("sid2", [], {})
    ])
    registry.register("a1", runner)
    init_sessions(registry)

    response = client.get("/agents/a1/sessions")
    assert response.status_code == 200
    data = response.json()
    assert len(data["sessions"]) == 2
    assert data["sessions"][0]["session_id"] == "sid1"
    assert data["sessions"][0]["message_count"] == 3
    assert data["sessions"][0]["state"] == {"foo": "bar"}

def test_list_sessions_agent_not_found():
    registry = AgentRegistry()
    init_sessions(registry) # Empty
    response = client.get("/agents/missing/sessions")
    assert response.status_code == 200
    data = response.json()
    assert data["sessions"] == []  # Return empty array when agent not in registry but dir might exist

def test_get_memory_not_implemented():
    response = client.get("/agents/a1/memory")
    assert response.status_code == 501
    assert "not yet implemented" in response.json()["detail"]
