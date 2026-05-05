"""GET /api/studio/dashboard/summary — single-aggregate BFF endpoint.

Locks down the BFF contract: one HTTP request returns counts +
distributions + activity for the whole workspace; ETag/304 short-
circuits a second identical request without rebuilding the payload.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ark_agentic.core.runtime.registry import AgentRegistry
from ark_agentic.core.storage.entries import (
    MemorySummaryEntry,
    SessionSummaryEntry,
)
from ark_agentic.plugins.api.deps import init_registry
from ark_agentic.plugins.studio.api.dashboard import (
    _cache,
    router as dashboard_router,
)


class _StubSessionManager:
    def __init__(self, summaries: list[SessionSummaryEntry]) -> None:
        self._summaries = summaries

    async def list_summaries_from_disk(self, user_id=None):
        return list(self._summaries)


class _StubMemoryManager:
    def __init__(self, summaries: list[MemorySummaryEntry], workspace: Path) -> None:
        self._summaries = summaries
        self.config = SimpleNamespace(workspace_dir=str(workspace))

    async def list_memory_summaries(self) -> list[MemorySummaryEntry]:
        return list(self._summaries)


class _StubRunner:
    def __init__(self, sm: _StubSessionManager, mm: _StubMemoryManager | None) -> None:
        self.session_manager = sm
        self._memory_manager = mm

    @property
    def memory_manager(self) -> _StubMemoryManager | None:
        return self._memory_manager


@pytest.fixture(autouse=True)
def _reset_dashboard_cache():
    _cache["payload"] = None
    _cache["etag"] = None
    _cache["at"] = 0.0
    yield
    _cache["payload"] = None
    _cache["etag"] = None
    _cache["at"] = 0.0


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> FastAPI:
    """Mount the dashboard router with an agents tree on disk + stub runners."""
    agents_root = tmp_path / "agents"
    agents_root.mkdir()
    for agent_id, name in [("alpha", "Alpha"), ("beta", "Beta")]:
        d = agents_root / agent_id
        (d / "skills").mkdir(parents=True)
        (d / "tools").mkdir()
        (d / "agent.json").write_text(
            f'{{"id":"{agent_id}","name":"{name}","status":"active",'
            f'"created_at":"","updated_at":""}}',
            encoding="utf-8",
        )

    monkeypatch.setattr(
        "ark_agentic.plugins.studio.api.dashboard.get_agents_root",
        lambda *_a, **_kw: agents_root,
    )

    registry = AgentRegistry()
    registry.register("alpha", _StubRunner(
        sm=_StubSessionManager([
            SessionSummaryEntry(
                session_id="s_alpha_1", user_id="u1", updated_at=2_000,
                message_count=3, first_user_message="hi alpha",
                model="m", provider="p",
            ),
        ]),
        mm=_StubMemoryManager(
            [MemorySummaryEntry(user_id="u1", size_bytes=42, updated_at=2_000)],
            tmp_path,
        ),
    ))
    registry.register("beta", _StubRunner(
        sm=_StubSessionManager([
            SessionSummaryEntry(
                session_id="s_beta_1", user_id="u2", updated_at=1_000,
                message_count=0, first_user_message=None,
                model="m", provider="p",
            ),
            SessionSummaryEntry(
                session_id="s_beta_2", user_id="u3", updated_at=3_000,
                message_count=12, first_user_message="hello beta",
                model="m", provider="p",
            ),
        ]),
        mm=None,
    ))
    init_registry(registry)

    fastapi_app = FastAPI()
    fastapi_app.include_router(dashboard_router, prefix="/api/studio")
    return fastapi_app


def test_dashboard_summary_aggregates_across_agents(
    app: FastAPI, studio_auth_context,
):
    client = TestClient(app)
    studio_auth_context(client=client)

    response = client.get("/api/studio/dashboard/summary")

    assert response.status_code == 200
    body = response.json()
    assert body["total_agents"] == 2
    assert body["total_sessions"] == 3
    assert body["total_users"] == 3
    assert body["total_memory_files"] == 1
    assert body["total_memory_bytes"] == 42

    bands = {b["label"]: b["value"] for b in body["sessions"]["message_bands"]}
    assert bands["0 messages"] == 1
    assert bands["1-5 messages"] == 1
    assert bands["6-20 messages"] == 1


def test_dashboard_summary_includes_workspace_memory_md_and_knowledge(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, studio_auth_context,
):
    """Global MEMORY.md and knowledge/*.md must count toward dashboard totals.

    Regression: the previous client-side aggregation walked
    ``GET /agents/{id}/memory/files`` which surfaced workspace-root
    ``MEMORY.md`` (file_type=memory) and ``memory/*.md`` (file_type=
    knowledge). The summary endpoint must keep that coverage.
    """
    agents_root = tmp_path / "agents"
    agents_root.mkdir()
    (agents_root / "alpha").mkdir()
    (agents_root / "alpha" / "skills").mkdir()
    (agents_root / "alpha" / "tools").mkdir()
    (agents_root / "alpha" / "agent.json").write_text(
        '{"id":"alpha","name":"Alpha","status":"active",'
        '"created_at":"","updated_at":""}',
        encoding="utf-8",
    )

    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "MEMORY.md").write_text("# global\n", encoding="utf-8")
    (workspace / "memory").mkdir()
    (workspace / "memory" / "topic.md").write_text(
        "# topic\nbody\n", encoding="utf-8",
    )

    monkeypatch.setattr(
        "ark_agentic.plugins.studio.api.dashboard.get_agents_root",
        lambda *_a, **_kw: agents_root,
    )

    registry = AgentRegistry()
    registry.register("alpha", _StubRunner(
        sm=_StubSessionManager([]),
        mm=_StubMemoryManager([], workspace),
    ))
    init_registry(registry)

    fastapi_app = FastAPI()
    fastapi_app.include_router(dashboard_router, prefix="/api/studio")

    client = TestClient(fastapi_app)
    studio_auth_context(client=client)

    body = client.get("/api/studio/dashboard/summary").json()

    expected_bytes = (
        len(b"# global\n") + len(b"# topic\nbody\n")
    )
    assert body["total_memory_files"] == 2
    assert body["total_memory_bytes"] == expected_bytes
    file_types = {ft["label"]: ft["value"] for ft in body["memory"]["file_types"]}
    assert file_types == {"memory": 1, "knowledge": 1}


def test_dashboard_summary_returns_etag_and_serves_304_on_revalidate(
    app: FastAPI, studio_auth_context,
):
    client = TestClient(app)
    studio_auth_context(client=client)

    first = client.get("/api/studio/dashboard/summary")
    etag = first.headers.get("etag")
    assert etag is not None

    revalidate = client.get(
        "/api/studio/dashboard/summary",
        headers={"If-None-Match": etag},
    )
    assert revalidate.status_code == 304
    assert revalidate.headers.get("etag") == etag
