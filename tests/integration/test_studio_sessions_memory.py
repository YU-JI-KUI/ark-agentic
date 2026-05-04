"""
Studio Sessions & Memory API tests.

Session API: view + edit only (no create/delete). List/detail use list_sessions_from_disk and load_session.
Tests use deps.init_registry() to inject a registry with a mock AgentRunner.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from ark_agentic.api.deps import init_registry
from ark_agentic.studio.api.sessions import router as sessions_router
from ark_agentic.studio.api.memory import _resolve_memory_path, router as memory_router
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
    def __init__(self, sid, msgs=None, state=None, user_id="", *, created_at=None, updated_at=None):
        self.session_id = sid
        self.user_id = user_id
        self.messages = msgs or []
        self.state = state or {}
        self.created_at = created_at
        self.updated_at = updated_at


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


class DummySessionRepository:
    """Repository facade over DummyTranscriptManager for the Studio raw endpoints."""

    def __init__(self, tm: "DummyTranscriptManager"):
        self._tm = tm

    async def get_raw_transcript(self, session_id: str, user_id: str) -> str | None:
        return self._tm.read_raw(session_id, user_id)

    async def put_raw_transcript(self, session_id: str, user_id: str, content: str) -> None:
        await self._tm.write_raw(session_id, user_id, content)


class DummySessionManager:
    def __init__(self, sessions=None, transcript_files=None):
        self._sessions = {s.session_id: s for s in (sessions or [])}
        self._transcript_manager = DummyTranscriptManager()
        if transcript_files:
            self._transcript_manager.files.update(transcript_files)
        self._repository = DummySessionRepository(self._transcript_manager)

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

    async def get_raw_transcript(self, sid, user_id):
        return await self._repository.get_raw_transcript(sid, user_id)

    async def put_raw_transcript(self, sid, user_id, content):
        await self._repository.put_raw_transcript(sid, user_id, content)


class DummyMemoryManager:
    """Minimal stand-in for MemoryManager (only workspace_dir needed by Studio API)."""

    def __init__(self, workspace_dir: Path) -> None:
        self.config = SimpleNamespace(workspace_dir=str(workspace_dir))
        self._dirty = False

    async def list_user_ids(self) -> list[str]:
        return []

    async def read_memory(self, user_id: str) -> str:
        return ""

    async def overwrite(self, user_id: str, content: str) -> None:
        pass

    def mark_dirty(self) -> None:
        self._dirty = True


class DummyAgentRunner:
    def __init__(self, sessions=None, transcript_files=None, memory_manager=None):
        self.session_manager = DummySessionManager(sessions, transcript_files)
        self._memory_manager = memory_manager

    @property
    def memory_manager(self):
        return self._memory_manager

    def mark_memory_dirty(self) -> None:
        if self._memory_manager:
            self._memory_manager.mark_dirty()


# ── Test setup ──────────────────────────────────────────────────────

app = FastAPI()
app.include_router(sessions_router, prefix="/api/studio")
app.include_router(memory_router, prefix="/api/studio")
client = TestClient(app)


VALID_JSONL_SID1 = '{"type":"session","id":"sid1","timestamp":"","cwd":""}\n{"type":"message","message":{"role":"user","content":"hi"},"timestamp":0}\n'


@pytest.fixture(autouse=True)
def setup_registry(tmp_path: Path, studio_auth_context):
    """Inject a clean registry before each test."""
    studio_auth_context(client=client)
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


# ── Memory API tests ────────────────────────────────────────────────

def _sessions_and_transcript():
    return [
        DummySession("sid1", [DummyMessage("user", "hi"), DummyMessage("assistant", "hello")], {"foo": "bar"}, user_id="u1"),
        DummySession("sid2", [], {}, user_id="u2"),
    ], {"sid1": VALID_JSONL_SID1}


def _register_insurance(*, memory_manager: DummyMemoryManager | None) -> None:
    registry = AgentRegistry()
    sessions, transcript_files = _sessions_and_transcript()
    runner = DummyAgentRunner(sessions, transcript_files, memory_manager=memory_manager)
    registry.register("insurance", runner)
    init_registry(registry)


def test_list_memory_files_empty_when_memory_disabled():
    """Runner without MemoryManager returns empty file list."""
    _register_insurance(memory_manager=None)
    response = client.get("/api/studio/agents/insurance/memory/files")
    assert response.status_code == 200
    assert response.json()["files"] == []


def test_list_memory_files_includes_workspace_memory_md(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "MEMORY.md").write_text("# Studio test\n", encoding="utf-8")
    _register_insurance(memory_manager=DummyMemoryManager(ws))
    response = client.get("/api/studio/agents/insurance/memory/files")
    assert response.status_code == 200
    paths = {f["file_path"] for f in response.json()["files"]}
    assert "MEMORY.md" in paths


def test_get_put_memory_content_roundtrip(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "MEMORY.md").write_text("# Before\n", encoding="utf-8")
    _register_insurance(memory_manager=DummyMemoryManager(ws))

    r_get = client.get(
        "/api/studio/agents/insurance/memory/content",
        params={"file_path": "MEMORY.md", "user_id": ""},
    )
    assert r_get.status_code == 200
    assert r_get.text == "# Before\n"

    r_put = client.put(
        "/api/studio/agents/insurance/memory/content",
        params={"file_path": "MEMORY.md", "user_id": ""},
        content="# After edit\n",
        headers={"Content-Type": "text/plain"},
    )
    assert r_put.status_code == 200
    assert r_put.json() == {"status": "saved"}

    r_verify = client.get(
        "/api/studio/agents/insurance/memory/content",
        params={"file_path": "MEMORY.md", "user_id": ""},
    )
    assert r_verify.status_code == 200
    assert r_verify.text == "# After edit\n"


def test_put_memory_content_missing_file_404(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "MEMORY.md").write_text("x", encoding="utf-8")
    _register_insurance(memory_manager=DummyMemoryManager(ws))
    response = client.put(
        "/api/studio/agents/insurance/memory/content",
        params={"file_path": "missing.md", "user_id": ""},
        content="nope",
        headers={"Content-Type": "text/plain"},
    )
    assert response.status_code == 404


def test_resolve_memory_path_rejects_traversal(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "MEMORY.md").write_text("ok", encoding="utf-8")
    with pytest.raises(HTTPException) as exc:
        _resolve_memory_path(ws, "../../../etc/passwd")
    assert exc.value.status_code == 403
    assert "traversal" in (exc.value.detail or "").lower()


def test_resolve_memory_path_allows_workspace_file(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    target = ws / "MEMORY.md"
    target.write_text("content", encoding="utf-8")
    resolved = _resolve_memory_path(ws, "MEMORY.md")
    assert resolved == target.resolve()
    assert resolved.read_text(encoding="utf-8") == "content"


async def test_list_memory_files_merges_sqlite_user_without_disk_md(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    studio_auth_context,
):
    """SQLite user_memory has rows but workspace has no U001/MEMORY.md — Studio still lists them."""
    from ark_agentic.core.db.engine import get_async_engine, init_schema, reset_engine_cache
    from ark_agentic.core.memory.manager import build_memory_manager

    db_path = tmp_path / "central.db"
    monkeypatch.setenv("DB_TYPE", "sqlite")
    monkeypatch.setenv("DB_CONNECTION_STR", f"sqlite+aiosqlite:///{db_path.as_posix()}")
    reset_engine_cache()
    try:
        engine = get_async_engine()
        await init_schema(engine)

        ws = tmp_path / "mem_workspace"
        ws.mkdir()
        mm = build_memory_manager(ws)
        await mm.overwrite("U001", "## SqliteOnly\ncontent\n")

        studio_auth_context(client=client)
        registry = AgentRegistry()
        sessions, transcript_files = _sessions_and_transcript()
        registry.register(
            "insurance",
            DummyAgentRunner(sessions, transcript_files, memory_manager=mm),
        )
        init_registry(registry)

        response = client.get("/api/studio/agents/insurance/memory/files")
        assert response.status_code == 200
        paths = {f["file_path"] for f in response.json()["files"]}
        assert "U001/MEMORY.md" in paths

        r2 = client.get(
            "/api/studio/agents/insurance/memory/content",
            params={"file_path": "U001/MEMORY.md", "user_id": "U001"},
        )
        assert r2.status_code == 200
        assert "SqliteOnly" in r2.text
    finally:
        reset_engine_cache()
