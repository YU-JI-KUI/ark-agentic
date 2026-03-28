"""
Studio Sessions & Memory API tests.

Session API: view + edit only (no create/delete). List/detail use list_sessions_from_disk and load_session.
Tests use deps.init_registry() to inject a registry with a mock AgentRunner.
"""

import json
import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI

from ark_agentic.api.deps import init_registry
from ark_agentic.studio.api.sessions import router as sessions_router
from ark_agentic.studio.api.memory import router as memory_router
from ark_agentic.core.registry import AgentRegistry
from ark_agentic.core.persistence import RawJsonlValidationError


# ── Dummy objects ───────────────────────────────────────────────────

class DummyMessage:
    def __init__(self, role, content, tool_calls=None, tool_results=None, thinking=None, metadata=None):
        self.role = role
        self.content = content
        self.tool_calls = tool_calls or []
        self.tool_results = tool_results or []
        self.thinking = thinking
        self.metadata = metadata or {}


class DummySession:
    def __init__(self, sid, msgs=None, state=None, user_id=""):
        self.session_id = sid
        self.user_id = user_id
        self.messages = msgs or []
        self.state = state or {}


class DummyTranscriptManager:
    """In-memory JSONL store for raw get/put tests. Mimics validation so 400 tests pass."""

    def __init__(self):
        self.files: dict[str, str] = {}

    def read_raw(self, session_id: str, user_id: str) -> str | None:
        return self.files.get(session_id)

    async def write_raw(self, session_id: str, user_id: str, content: str) -> None:
        lines = [line for line in content.splitlines() if line.strip()]
        if not lines:
            raise RawJsonlValidationError("至少需要一行（session header）", line_number=1)
        try:
            first = json.loads(lines[0])
        except json.JSONDecodeError as e:
            raise RawJsonlValidationError(f"首行非法 JSON: {e}", line_number=1) from e
        if first.get("type") != "session":
            raise RawJsonlValidationError("首行 type 必须为 session", line_number=1)
        if (first.get("id") or "").strip() != session_id.strip():
            raise RawJsonlValidationError("首行 id 与 URL session_id 不一致", line_number=1)
        self.files[session_id] = content


class DummySessionManager:
    def __init__(self, sessions=None, transcript_files=None):
        self._sessions = {s.session_id: s for s in (sessions or [])}
        self._transcript_manager = DummyTranscriptManager()
        if transcript_files:
            self._transcript_manager.files.update(transcript_files)

    def list_sessions(self):
        return list(self._sessions.values())

    async def list_sessions_from_disk(self, user_id=None):
        return list(self._sessions.values())

    def get_session(self, sid):
        return self._sessions.get(sid)

    async def load_session(self, sid, user_id):
        return self._sessions.get(sid)

    async def reload_session_from_disk(self, sid, user_id):
        return self._sessions.get(sid)


class DummyAgentRunner:
    def __init__(self, sessions=None, transcript_files=None):
        self.session_manager = DummySessionManager(sessions, transcript_files)


# ── Test setup ──────────────────────────────────────────────────────

app = FastAPI()
app.include_router(sessions_router, prefix="/api/studio")
app.include_router(memory_router, prefix="/api/studio")
client = TestClient(app)


VALID_JSONL_SID1 = '{"type":"session","id":"sid1","timestamp":"","cwd":""}\n{"type":"message","message":{"role":"user","content":"hi"},"timestamp":0}\n'


@pytest.fixture(autouse=True)
def setup_registry():
    """Inject a clean registry before each test."""
    registry = AgentRegistry()
    runner = DummyAgentRunner(
        [
            DummySession("sid1", [DummyMessage("user", "hi"), DummyMessage("assistant", "hello")], {"foo": "bar"}, user_id="u1"),
            DummySession("sid2", [], {}, user_id="u2"),
        ],
        transcript_files={"sid1": VALID_JSONL_SID1},
    )
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
    assert data["sessions"][0]["user_id"] == "u1"
    assert data["sessions"][0]["message_count"] == 2
    assert data["sessions"][0]["state"] == {"foo": "bar"}
    assert data["sessions"][1]["user_id"] == "u2"


def test_list_sessions_agent_not_found():
    response = client.get("/api/studio/agents/missing/sessions")
    assert response.status_code == 200
    data = response.json()
    assert data["sessions"] == []


# ── Session detail tests ────────────────────────────────────────────

def test_get_session_detail():
    response = client.get("/api/studio/agents/insurance/sessions/sid1?user_id=test_user")
    assert response.status_code == 200
    data = response.json()
    assert data["session_id"] == "sid1"
    assert len(data["messages"]) == 2
    assert data["messages"][0]["role"] == "user"
    assert data["messages"][0]["content"] == "hi"


def test_get_session_detail_not_found():
    response = client.get("/api/studio/agents/insurance/sessions/nonexistent?user_id=test_user")
    assert response.status_code == 404


# ── Session raw GET/PUT tests ───────────────────────────────────────

def test_get_session_raw_success():
    response = client.get("/api/studio/agents/insurance/sessions/sid1/raw?user_id=test_user")
    assert response.status_code == 200
    assert "session" in response.text
    assert "sid1" in response.text


def test_get_session_raw_not_found():
    response = client.get("/api/studio/agents/insurance/sessions/nonexistent/raw?user_id=test_user")
    assert response.status_code == 404


def test_put_session_raw_valid():
    body = '{"type":"session","id":"sid1","timestamp":"","cwd":""}\n'
    response = client.put(
        "/api/studio/agents/insurance/sessions/sid1/raw?user_id=test_user",
        content=body,
        headers={"Content-Type": "text/plain"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "saved"
    assert data["session_id"] == "sid1"
    # Verify GET raw returns the new content
    r2 = client.get("/api/studio/agents/insurance/sessions/sid1/raw?user_id=test_user")
    assert r2.status_code == 200
    assert r2.text.strip() == body.strip()


def test_put_session_raw_invalid_first_line_type():
    body = '{"type":"message","message":{}}\n'
    response = client.put(
        "/api/studio/agents/insurance/sessions/sid1/raw?user_id=test_user",
        content=body,
        headers={"Content-Type": "text/plain"},
    )
    assert response.status_code == 400
    detail = response.json().get("detail", {})
    if isinstance(detail, dict):
        assert "message" in detail or "line_number" in detail or "type" in str(detail).lower()


def test_put_session_raw_id_mismatch():
    body = '{"type":"session","id":"other","timestamp":"","cwd":""}\n'
    response = client.put(
        "/api/studio/agents/insurance/sessions/sid1/raw?user_id=test_user",
        content=body,
        headers={"Content-Type": "text/plain"},
    )
    assert response.status_code == 400


# ── Memory tests (unchanged) ───────────────────────────────────────

def test_get_memory_not_implemented():
    response = client.get("/api/studio/agents/insurance/memory")
    assert response.status_code == 501
    assert "not yet implemented" in response.json()["detail"]
