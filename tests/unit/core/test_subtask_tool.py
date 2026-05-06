"""Tests for SpawnSubtasksTool (batched parallel subtasks)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ark_agentic.core.runtime.runner import AgentRunner, RunnerConfig, RunResult
from ark_agentic.core.session import SessionManager
from ark_agentic.core.subtask.tool import SpawnSubtasksTool, SubtaskConfig, _SUBTASK_SESSION_MARKER
from ark_agentic.core.tools.base import AgentTool
from ark_agentic.core.tools.registry import ToolRegistry
from ark_agentic.core.types import AgentMessage, AgentToolResult, ToolCall


@pytest.fixture
def session_manager(tmp_path: Path) -> SessionManager:
    return SessionManager(tmp_path / "sessions")


class _DummyTool(AgentTool):
    name = "dummy"
    description = "dummy"
    parameters = []

    async def execute(self, tool_call: ToolCall, context: dict | None = None) -> AgentToolResult:
        return AgentToolResult.json_result(tool_call.id, {"result": "ok"})


class _AlphaTool(AgentTool):
    name = "alpha"
    description = "alpha tool"
    parameters = []

    async def execute(self, tool_call: ToolCall, context: dict | None = None) -> AgentToolResult:
        return AgentToolResult.json_result(tool_call.id, {"result": "ok"})


class _BraveTool(AgentTool):
    name = "brave"
    description = "brave tool"
    parameters = []

    async def execute(self, tool_call: ToolCall, context: dict | None = None) -> AgentToolResult:
        return AgentToolResult.json_result(tool_call.id, {"result": "ok"})


def _make_mock_runner(session_manager: SessionManager, tools: list[AgentTool] | None = None) -> AgentRunner:
    llm = MagicMock()
    registry = ToolRegistry()
    for t in (tools or [_DummyTool()]):
        registry.register(t)
    runner = AgentRunner.__new__(AgentRunner)
    runner.llm = llm
    runner.tool_registry = registry
    runner.session_manager = session_manager
    runner.skill_loader = None
    runner.config = RunnerConfig()
    runner._memory_manager = None
    runner._callbacks = MagicMock()
    runner._llm_caller = MagicMock()
    runner._tool_executor = MagicMock()
    runner._flusher = None
    runner.skill_matcher = None
    return runner


@pytest.fixture
def mock_runner(session_manager: SessionManager) -> AgentRunner:
    return _make_mock_runner(session_manager)


@pytest.mark.asyncio
async def test_nesting_rejected(session_manager: SessionManager, mock_runner: AgentRunner) -> None:
    """Subtask cannot spawn subtasks (nesting prevention)."""
    tool = SpawnSubtasksTool(mock_runner, session_manager)
    tc = ToolCall.create("spawn_subtasks", {
        "tasks": [{"task": "do something", "label": "t1"}],
    })
    # Parent session_id contains :sub: marker
    ctx = {"session_id": f"parent{_SUBTASK_SESSION_MARKER}abc123"}
    result = await tool.execute(tc, ctx)
    assert "nesting" in result.content.get("error", "")


@pytest.mark.asyncio
async def test_empty_tasks_list(session_manager: SessionManager, mock_runner: AgentRunner) -> None:
    tool = SpawnSubtasksTool(mock_runner, session_manager)
    tc = ToolCall.create("spawn_subtasks", {"tasks": []})
    result = await tool.execute(tc, {"session_id": "parent-001"})
    assert "empty" in result.content.get("error", "")


@pytest.mark.asyncio
async def test_empty_task_description(session_manager: SessionManager, mock_runner: AgentRunner) -> None:
    tool = SpawnSubtasksTool(mock_runner, session_manager)
    tc = ToolCall.create("spawn_subtasks", {
        "tasks": [{"task": "", "label": "empty"}],
    })
    parent_session = session_manager.create_session_sync(session_id="parent-002", user_id="u1")
    result = await tool.execute(tc, {"session_id": "parent-002"})
    subtasks = result.content.get("subtasks", [])
    assert len(subtasks) == 1
    assert subtasks[0]["status"] == "error"
    assert "empty" in subtasks[0]["error"]


@pytest.mark.asyncio
async def test_successful_single_subtask(session_manager: SessionManager, mock_runner: AgentRunner) -> None:
    """Single subtask executes and returns result."""
    parent_session = session_manager.create_session_sync(
        session_id="parent-003", user_id="user_A",
        state={"user:id": "user_A", "user:name": "Alice", "temp:foo": "bar"},
    )

    run_result = RunResult(
        response=AgentMessage.assistant("subtask answer"),
        turns=2,
        tool_calls_count=1,
    )

    with patch.object(AgentRunner, "run_ephemeral", new_callable=AsyncMock, return_value=run_result):
        tool = SpawnSubtasksTool(mock_runner, session_manager)
        tc = ToolCall.create("spawn_subtasks", {
            "tasks": [{"task": "analyze policy P001", "label": "P001"}],
        })
        result = await tool.execute(tc, {"session_id": "parent-003"})

    subtasks = result.content.get("subtasks", [])
    assert len(subtasks) == 1
    assert subtasks[0]["status"] == "completed"
    assert subtasks[0]["label"] == "P001"
    assert subtasks[0]["result"] == "subtask answer"
    assert subtasks[0]["execution"]["turns"] == 2


@pytest.mark.asyncio
async def test_parallel_subtasks_execution(session_manager: SessionManager, mock_runner: AgentRunner) -> None:
    """Multiple subtasks run in parallel."""
    parent_session = session_manager.create_session_sync(
        session_id="parent-004", user_id="user_B",
        state={"user:id": "user_B"},
    )

    call_count = 0

    async def fake_run_ephemeral(self, session_id: str, user_input: str) -> RunResult:
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0.05)
        return RunResult(
            response=AgentMessage.assistant(f"result for: {user_input[:20]}"),
            turns=1,
            tool_calls_count=0,
        )

    with patch.object(AgentRunner, "run_ephemeral", fake_run_ephemeral):
        tool = SpawnSubtasksTool(mock_runner, session_manager)
        tc = ToolCall.create("spawn_subtasks", {
            "tasks": [
                {"task": "task A - claims", "label": "claims"},
                {"task": "task B - query balance", "label": "balance"},
            ],
        })
        result = await tool.execute(tc, {"session_id": "parent-004"})

    subtasks = result.content.get("subtasks", [])
    assert len(subtasks) == 2
    assert call_count == 2
    labels = {s["label"] for s in subtasks}
    assert labels == {"claims", "balance"}
    assert all(s["status"] == "completed" for s in subtasks)


@pytest.mark.asyncio
async def test_state_inheritance_and_delta(session_manager: SessionManager, mock_runner: AgentRunner) -> None:
    """Sub-session inherits user:* state. state_delta returned for changed keys."""
    parent_session = session_manager.create_session_sync(
        session_id="parent-005", user_id="user_C",
        state={"user:id": "user_C", "user:level": "vip", "temp:draft": "x"},
    )

    async def fake_run_ephemeral(self, session_id: str, user_input: str) -> RunResult:
        sub_session = self.session_manager.get_session(session_id)
        if sub_session:
            assert "user:id" in sub_session.state
            assert "user:level" in sub_session.state
            assert "temp:draft" not in sub_session.state
            sub_session.state["new_key"] = "new_val"
        return RunResult(
            response=AgentMessage.assistant("done"),
            turns=1,
        )

    with patch.object(AgentRunner, "run_ephemeral", fake_run_ephemeral):
        tool = SpawnSubtasksTool(mock_runner, session_manager)
        tc = ToolCall.create("spawn_subtasks", {
            "tasks": [{"task": "check state", "label": "state_test"}],
        })
        result = await tool.execute(tc, {"session_id": "parent-005"})

    subtasks = result.content.get("subtasks", [])
    assert subtasks[0]["status"] == "completed"

    state_delta = result.metadata.get("state_delta", {}) if result.metadata else {}
    assert state_delta.get("new_key") == "new_val"


@pytest.mark.asyncio
async def test_token_aggregation(session_manager: SessionManager, mock_runner: AgentRunner) -> None:
    """Subtask tokens are aggregated to parent session."""
    parent_session = session_manager.create_session_sync(
        session_id="parent-006", user_id="user_D",
    )

    async def fake_run_ephemeral(self, session_id: str, user_input: str) -> RunResult:
        return RunResult(
            response=AgentMessage.assistant("ok"),
            turns=1,
        )

    with patch.object(AgentRunner, "run_ephemeral", fake_run_ephemeral):
        tool = SpawnSubtasksTool(mock_runner, session_manager)
        tc = ToolCall.create("spawn_subtasks", {
            "tasks": [
                {"task": "t1", "label": "a"},
                {"task": "t2", "label": "b"},
            ],
        })
        result = await tool.execute(tc, {"session_id": "parent-006"})


@pytest.mark.asyncio
async def test_sub_session_cleanup(session_manager: SessionManager, mock_runner: AgentRunner) -> None:
    """Sub-sessions are deleted after subtask completes (keep_session=False)."""
    parent_session = session_manager.create_session_sync(
        session_id="parent-007", user_id="user_E",
    )

    created_session_ids: list[str] = []
    original_create = session_manager.create_session_sync

    def tracking_create(*args, **kwargs):
        s = original_create(*args, **kwargs)
        if _SUBTASK_SESSION_MARKER in s.session_id:
            created_session_ids.append(s.session_id)
        return s

    session_manager.create_session_sync = tracking_create

    async def fake_run_ephemeral(self, session_id: str, user_input: str) -> RunResult:
        return RunResult(response=AgentMessage.assistant("done"), turns=1)

    with patch.object(AgentRunner, "run_ephemeral", fake_run_ephemeral):
        tool = SpawnSubtasksTool(mock_runner, session_manager, SubtaskConfig(keep_session=False))
        tc = ToolCall.create("spawn_subtasks", {
            "tasks": [{"task": "temp task", "label": "t"}],
        })
        await tool.execute(tc, {"session_id": "parent-007"})

    assert len(created_session_ids) == 1
    assert session_manager.get_session(created_session_ids[0]) is None


@pytest.mark.asyncio
async def test_deny_list_excludes_spawn_subtasks(session_manager: SessionManager, mock_runner: AgentRunner) -> None:
    """spawn_subtasks is always excluded from sub-runner's tool registry."""
    parent_session = session_manager.create_session_sync(
        session_id="parent-008", user_id="user_F",
    )

    captured_registries: list[ToolRegistry] = []
    original_init = AgentRunner.__init__

    def capture_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        captured_registries.append(self.tool_registry)

    async def fake_run_ephemeral(self, session_id: str, user_input: str) -> RunResult:
        return RunResult(response=AgentMessage.assistant("ok"), turns=1)

    with patch.object(AgentRunner, "__init__", capture_init), \
         patch.object(AgentRunner, "run_ephemeral", fake_run_ephemeral):
        tool = SpawnSubtasksTool(mock_runner, session_manager)
        tc = ToolCall.create("spawn_subtasks", {
            "tasks": [{"task": "test deny", "label": "d"}],
        })
        await tool.execute(tc, {"session_id": "parent-008"})

    # The sub-runner's registry should not contain spawn_subtasks
    assert len(captured_registries) >= 1
    sub_reg = captured_registries[-1]
    assert not sub_reg.has("spawn_subtasks")


@pytest.mark.asyncio
async def test_subtask_runner_does_not_inherit_parent_callbacks(
    session_manager: SessionManager,
) -> None:
    """Subtask runner should rebuild its own internal callbacks, not reuse parent callbacks."""
    runner = _make_mock_runner(session_manager, [_DummyTool()])
    parent_session = session_manager.create_session_sync(
        session_id="parent-008b", user_id="user_F2",
    )

    captured_callback_args: list[object | None] = []
    original_init = AgentRunner.__init__

    def capture_init(self, *args, **kwargs):
        captured_callback_args.append(kwargs.get("callbacks"))
        original_init(self, *args, **kwargs)

    async def fake_run_ephemeral(self, session_id: str, user_input: str) -> RunResult:
        return RunResult(response=AgentMessage.assistant("ok"), turns=1)

    with patch.object(AgentRunner, "__init__", capture_init), \
         patch.object(AgentRunner, "run_ephemeral", fake_run_ephemeral):
        tool = SpawnSubtasksTool(runner, session_manager)
        tc = ToolCall.create("spawn_subtasks", {
            "tasks": [{"task": "test callbacks", "label": "cb"}],
        })
        await tool.execute(tc, {"session_id": "parent-008b"})

    assert captured_callback_args[-1] is None


@pytest.mark.asyncio
async def test_subtask_timeout(session_manager: SessionManager, mock_runner: AgentRunner) -> None:
    """Subtask that exceeds timeout returns timed_out status."""
    parent_session = session_manager.create_session_sync(
        session_id="parent-009", user_id="user_G",
    )

    async def slow_run_ephemeral(self, session_id: str, user_input: str) -> RunResult:
        await asyncio.sleep(5)
        return RunResult(response=AgentMessage.assistant("late"), turns=1)

    config = SubtaskConfig(timeout_seconds=0.1)
    with patch.object(AgentRunner, "run_ephemeral", slow_run_ephemeral):
        tool = SpawnSubtasksTool(mock_runner, session_manager, config)
        tc = ToolCall.create("spawn_subtasks", {
            "tasks": [{"task": "slow task", "label": "slow"}],
        })
        result = await tool.execute(tc, {"session_id": "parent-009"})

    subtasks = result.content.get("subtasks", [])
    assert len(subtasks) == 1
    assert subtasks[0]["status"] == "timed_out"


@pytest.mark.asyncio
async def test_persist_transcript_in_metadata(session_manager: SessionManager, mock_runner: AgentRunner) -> None:
    """When persist_transcript=True, transcript is included in metadata."""
    parent_session = session_manager.create_session_sync(
        session_id="parent-010", user_id="user_H",
    )

    async def fake_run_ephemeral(self, session_id: str, user_input: str) -> RunResult:
        sub = self.session_manager.get_session(session_id)
        if sub:
            sub.add_message(AgentMessage.user(user_input))
            sub.add_message(AgentMessage.assistant("answer"))
        return RunResult(
            response=AgentMessage.assistant("answer"),
            turns=1,
        )

    config = SubtaskConfig(persist_transcript=True)
    with patch.object(AgentRunner, "run_ephemeral", fake_run_ephemeral):
        tool = SpawnSubtasksTool(mock_runner, session_manager, config)
        tc = ToolCall.create("spawn_subtasks", {
            "tasks": [{"task": "transcript test", "label": "tr"}],
        })
        result = await tool.execute(tc, {"session_id": "parent-010"})

    transcripts = result.metadata.get("transcripts", {}) if result.metadata else {}
    assert "tr" in transcripts
    assert len(transcripts["tr"]) >= 2


# ============ tools whitelist (Phase 2) ============


@pytest.mark.asyncio
async def test_tools_whitelist_filters_registry(session_manager: SessionManager) -> None:
    """When task spec includes 'tools', sub-runner only gets those tools."""
    runner = _make_mock_runner(session_manager, [_DummyTool(), _AlphaTool(), _BraveTool()])
    parent_session = session_manager.create_session_sync(
        session_id="parent-wl1", user_id="u1",
    )

    captured_registries: list[ToolRegistry] = []
    original_init = AgentRunner.__init__

    def capture_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        captured_registries.append(self.tool_registry)

    async def fake_run_ephemeral(self, session_id: str, user_input: str) -> RunResult:
        return RunResult(response=AgentMessage.assistant("ok"), turns=1)

    with patch.object(AgentRunner, "__init__", capture_init), \
         patch.object(AgentRunner, "run_ephemeral", fake_run_ephemeral):
        tool = SpawnSubtasksTool(runner, session_manager)
        tc = ToolCall.create("spawn_subtasks", {
            "tasks": [{"task": "use alpha only", "label": "wl", "tools": ["alpha"]}],
        })
        await tool.execute(tc, {"session_id": "parent-wl1"})

    assert len(captured_registries) >= 1
    sub_reg = captured_registries[-1]
    sub_tool_names = {t.name for t in sub_reg.list_all()}
    assert "alpha" in sub_tool_names
    assert "brave" not in sub_tool_names
    assert "dummy" not in sub_tool_names


@pytest.mark.asyncio
async def test_tools_omitted_inherits_all(session_manager: SessionManager) -> None:
    """When task spec omits 'tools', sub-runner inherits all (minus deny)."""
    runner = _make_mock_runner(session_manager, [_DummyTool(), _AlphaTool(), _BraveTool()])
    parent_session = session_manager.create_session_sync(
        session_id="parent-wl2", user_id="u2",
    )

    captured_registries: list[ToolRegistry] = []
    original_init = AgentRunner.__init__

    def capture_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        captured_registries.append(self.tool_registry)

    async def fake_run_ephemeral(self, session_id: str, user_input: str) -> RunResult:
        return RunResult(response=AgentMessage.assistant("ok"), turns=1)

    with patch.object(AgentRunner, "__init__", capture_init), \
         patch.object(AgentRunner, "run_ephemeral", fake_run_ephemeral):
        tool = SpawnSubtasksTool(runner, session_manager)
        tc = ToolCall.create("spawn_subtasks", {
            "tasks": [{"task": "inherit all", "label": "inherit"}],
        })
        await tool.execute(tc, {"session_id": "parent-wl2"})

    assert len(captured_registries) >= 1
    sub_reg = captured_registries[-1]
    sub_tool_names = {t.name for t in sub_reg.list_all()}
    assert "dummy" in sub_tool_names
    assert "alpha" in sub_tool_names
    assert "brave" in sub_tool_names
    assert "spawn_subtasks" not in sub_tool_names


@pytest.mark.asyncio
async def test_tools_empty_list_inherits_all(session_manager: SessionManager) -> None:
    """When task spec has 'tools: []', it's treated as omitted → inherit all."""
    runner = _make_mock_runner(session_manager, [_DummyTool(), _AlphaTool()])
    parent_session = session_manager.create_session_sync(
        session_id="parent-wl3", user_id="u3",
    )

    captured_registries: list[ToolRegistry] = []
    original_init = AgentRunner.__init__

    def capture_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        captured_registries.append(self.tool_registry)

    async def fake_run_ephemeral(self, session_id: str, user_input: str) -> RunResult:
        return RunResult(response=AgentMessage.assistant("ok"), turns=1)

    with patch.object(AgentRunner, "__init__", capture_init), \
         patch.object(AgentRunner, "run_ephemeral", fake_run_ephemeral):
        tool = SpawnSubtasksTool(runner, session_manager)
        tc = ToolCall.create("spawn_subtasks", {
            "tasks": [{"task": "empty tools", "label": "et", "tools": []}],
        })
        await tool.execute(tc, {"session_id": "parent-wl3"})

    assert len(captured_registries) >= 1
    sub_reg = captured_registries[-1]
    sub_tool_names = {t.name for t in sub_reg.list_all()}
    assert "dummy" in sub_tool_names
    assert "alpha" in sub_tool_names
