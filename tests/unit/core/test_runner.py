"""Tests for AgentRunner core happy paths with ChatOpenAI backend."""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from typing import Any, AsyncIterator
import asyncio

import json

from ark_agentic.core.callbacks import CallbackContext, CallbackResult, RunnerCallbacks
from ark_agentic.core.runner import AgentRunner, RunnerConfig, RunResult
from ark_agentic.core.session import SessionManager
from ark_agentic.core.tools.base import AgentTool, ToolParameter
from ark_agentic.core.tools.registry import ToolRegistry
from ark_agentic.core.types import (
    AgentMessage,
    AgentToolResult,
    ToolCall,
    MessageRole,
    ToolResultType,
)
from langchain_core.messages import AIMessage, AIMessageChunk


# ============ Mock Tools ============


class _MockTool(AgentTool):
    """Minimal tool for testing."""

    name = "mock_tool"
    description = "A mock tool for testing"
    parameters = [
        ToolParameter(name="key", type="string", description="A test key"),
    ]

    async def execute(
        self, tool_call: ToolCall, context: dict[str, Any]
    ) -> AgentToolResult:
        return AgentToolResult(
            tool_call_id=tool_call.id,
            result_type="json",
            content={
                "result": f"processed_{context.get('input_val', 'default')}",
                "total_assets": 150000,
            },
            metadata={"tool_name": self.name},
        )


# ============ Mock LangChain LLM ============


class MockChatModel:
    """Mocks LangChain ChatOpenAI interface for native compatibility without external calls."""

    def __init__(self, responses: list[Any], stream_responses: list[list[Any]] = None):
        self.responses = responses
        self.stream_responses = stream_responses or []
        self.call_count = 0
        self.stream_call_count = 0

    def bind_tools(self, tools: list[dict[str, Any]], **kwargs) -> "MockChatModel":
        return self

    def model_copy(self, update: dict[str, Any] = None) -> "MockChatModel":
        return self

    async def ainvoke(self, messages: list[Any], **kwargs) -> AIMessage:
        if self.call_count >= len(self.responses):
            raise RuntimeError("ainvoke called more times than responses provided")
        res = self.responses[self.call_count]
        self.call_count += 1
        return res

    async def astream(
        self, messages: list[Any], **kwargs
    ) -> AsyncIterator[AIMessageChunk]:
        if self.stream_call_count >= len(self.stream_responses):
            raise RuntimeError(
                "astream called more times than stream_responses provided"
            )
        chunks = self.stream_responses[self.stream_call_count]
        self.stream_call_count += 1
        for chunk in chunks:
            yield chunk


# ============ Helpers ============


def _make_runner(
    sessions_dir: Path,
    responses: list[Any] = None,
    stream_responses: list[list[Any]] = None,
    callbacks: RunnerCallbacks | None = None,
) -> tuple[AgentRunner, _MockTool]:
    """Create a fresh AgentRunner with mock dependencies."""
    mock_llm = MockChatModel(
        responses=responses or [], stream_responses=stream_responses or []
    )
    llm = mock_llm  # type: ignore[arg-type]  # duck-typed BaseChatModel for tests
    registry = ToolRegistry()
    tool = _MockTool()
    registry.register(tool)
    session_mgr = SessionManager(sessions_dir)
    config = RunnerConfig(
        max_turns=5,
        auto_compact=False,
    )
    runner = AgentRunner(
        llm=llm,
        session_manager=session_mgr,
        tool_registry=registry,
        config=config,
        callbacks=callbacks,
    )
    return runner, tool


# ============ Tests ============


@pytest.mark.asyncio
async def test_run_basic_text_response(tmp_sessions_dir: Path) -> None:
    # Arrange
    responses = [AIMessage(content="Hello! I am a helpful agent.")]
    runner, _ = _make_runner(tmp_sessions_dir, responses=responses)
    session = runner.session_manager.create_session_sync()

    # Act
    result = await runner.run(
        session.session_id, "Who are you?", user_id="test_user", stream=False
    )

    # Assert
    assert result.response.content == "Hello! I am a helpful agent."
    assert result.turns == 1
    assert result.tool_calls_count == 0


@pytest.mark.asyncio
async def test_run_with_tool_call(tmp_sessions_dir: Path) -> None:
    # Arrange
    responses = [
        AIMessage(
            content="",
            tool_calls=[
                {"name": "mock_tool", "args": {"key": "test_key"}, "id": "call_123"}
            ],
        ),
        AIMessage(content="I have processed your request using the tool."),
    ]
    runner, _ = _make_runner(tmp_sessions_dir, responses=responses)
    session = runner.session_manager.create_session_sync()

    # Act
    result = await runner.run(
        session.session_id,
        "Use the tool!",
        user_id="test_user",
        stream=False,
        input_context={"input_val": "123"},
    )

    # Assert

    assert result.response.content == "I have processed your request using the tool."
    assert result.turns == 2
    assert result.tool_calls_count == 1

    # Verify the tool result got appended to session history correctly
    history = runner.session_manager.get_session(session.session_id).messages
    tool_msg = next((m for m in history if m.role == MessageRole.TOOL), None)
    assert tool_msg is not None
    assert tool_msg.tool_results[0].tool_call_id == "call_123"
    assert "processed_123" in tool_msg.tool_results[0].content["result"]


@pytest.mark.asyncio
async def test_run_streaming_text_response(tmp_sessions_dir: Path) -> None:
    # Arrange
    stream_responses = [
        [
            AIMessageChunk(content="Hello"),
            AIMessageChunk(content=" World"),
            AIMessageChunk(content="!"),
        ]
    ]
    runner, _ = _make_runner(tmp_sessions_dir, stream_responses=stream_responses)
    session = runner.session_manager.create_session_sync()

    captured_deltas = []

    class MockHandler:
        def on_content_delta(self, delta: str, turn: int = 1) -> None:
            captured_deltas.append(delta)

        def on_tool_call_start(self, tool_call_id: str, name: str, args: str) -> None:
            pass

        def on_tool_call_result(
            self, tool_call_id: str, name: str, result: str
        ) -> None:
            pass

        def on_step(self, status: str) -> None:
            pass

        def on_ui_component(self, component: dict) -> None:
            pass

    # Act
    result = await runner.run(
        session.session_id,
        "Greeting",
        user_id="test_user",
        stream=True,
        handler=MockHandler(),
    )

    # Assert

    assert result.response.content == "Hello World!"
    assert result.turns == 1
    assert captured_deltas == ["Hello", " World", "!"]


@pytest.mark.asyncio
async def test_run_streaming_with_tool_call(tmp_sessions_dir: Path) -> None:
    # Arrange
    stream_responses = [
        # Turn 1: Steaming tool call chunk
        [
            AIMessageChunk(
                content="",
                tool_call_chunks=[
                    {
                        "name": "mock_tool",
                        "args": '{"key": "test"}',
                        "id": "call_abc",
                        "index": 0,
                    }
                ],
            )
        ],
        # Turn 2: Steaming final answer
        [AIMessageChunk(content="Done "), AIMessageChunk(content="processing.")],
    ]
    runner, _ = _make_runner(tmp_sessions_dir, stream_responses=stream_responses)
    session = runner.session_manager.create_session_sync()

    captured_deltas = []
    captured_tool_starts = []
    captured_steps = []

    class MockHandler:
        def on_content_delta(self, delta: str, turn: int = 1) -> None:
            captured_deltas.append(delta)

        def on_tool_call_start(self, tool_call_id: str, name: str, args: str) -> None:
            captured_tool_starts.append(name)

        def on_tool_call_result(
            self, tool_call_id: str, name: str, result: str
        ) -> None:
            pass

        def on_step(self, status: str) -> None:
            captured_steps.append(status)

        def on_ui_component(self, component: dict) -> None:
            pass

    # Act
    result = await runner.run(
        session.session_id,
        "Use tool",
        user_id="test_user",
        stream=True,
        handler=MockHandler(),
        input_context={"input_val": "abc"},
    )

    # Assert

    assert result.response.content == "Done processing."
    assert result.turns == 2
    assert result.tool_calls_count == 1

    assert captured_deltas == ["Done ", "processing."]
    assert captured_tool_starts == ["mock_tool"]
    # Verify on_step was called (mock_tool has no thinking_hint → fallback)
    assert len(captured_steps) > 0
    assert any("mock_tool" in s for s in captured_steps), (
        "on_step should show tool name when thinking_hint is empty"
    )


@pytest.mark.asyncio
async def test_execute_tools_on_step_uses_tool_thinking_hint(
    tmp_sessions_dir: Path,
) -> None:
    """When a tool defines thinking_hint, on_step is called with that text."""

    class ToolWithHint(AgentTool):
        name = "hint_tool"
        description = "Tool with thinking hint"
        thinking_hint = "正在查询保单信息…"
        parameters = [
            ToolParameter(name="key", type="string", description="key"),
        ]

        async def execute(
            self, tool_call: ToolCall, context: dict[str, Any] | None = None
        ) -> AgentToolResult:
            return AgentToolResult(
                tool_call_id=tool_call.id, result_type="json", content={"ok": True}
            )

    stream_responses = [
        [
            AIMessageChunk(
                content="",
                tool_call_chunks=[
                    {
                        "name": "hint_tool",
                        "args": '{"key": "x"}',
                        "id": "call_1",
                        "index": 0,
                    }
                ],
            )
        ],
        [AIMessageChunk(content="Done.")],
    ]
    mock_llm = MockChatModel(responses=[], stream_responses=stream_responses)
    registry = ToolRegistry()
    registry.register(ToolWithHint())
    session_mgr = SessionManager(tmp_sessions_dir)
    runner = AgentRunner(
        llm=mock_llm,  # type: ignore[arg-type]
        session_manager=session_mgr,
        tool_registry=registry,
        config=RunnerConfig(max_turns=5, auto_compact=False),
    )
    session = runner.session_manager.create_session_sync()
    captured_steps: list[str] = []

    class MockHandler:
        def on_content_delta(self, delta: str, turn: int = 1) -> None:
            pass

        def on_tool_call_start(self, tool_call_id: str, name: str, args: Any) -> None:
            pass

        def on_tool_call_result(
            self, tool_call_id: str, name: str, result: Any
        ) -> None:
            pass

        def on_step(self, status: str) -> None:
            captured_steps.append(status)

        def on_ui_component(self, component: dict) -> None:
            pass

    await runner.run(
        session.session_id,
        "Use hint_tool",
        user_id="test_user",
        stream=True,
        handler=MockHandler(),
    )

    assert "正在查询保单信息…" in captured_steps, (
        f"on_step should be called with tool.thinking_hint, got: {captured_steps}"
    )


# ============ State Mechanism Tests ============


class _StateDeltaTool(AgentTool):
    """Tool that writes state_delta in result metadata."""

    name = "state_delta_tool"
    description = "A tool that returns state_delta"
    parameters = [
        ToolParameter(name="key", type="string", description="ignored"),
    ]

    async def execute(
        self, tool_call: ToolCall, context: dict[str, Any] | None = None
    ) -> AgentToolResult:
        return AgentToolResult(
            tool_call_id=tool_call.id,
            result_type="json",
            content={"ok": True},
            metadata={"state_delta": {"auth_token": "tok_abc", "user:name": "Alice"}},
        )


@pytest.mark.asyncio
async def test_state_delta_merge(tmp_sessions_dir: Path) -> None:
    """Tool's state_delta is merged into session.state and visible in next turn."""
    responses = [
        AIMessage(
            content="",
            tool_calls=[
                {"name": "state_delta_tool", "args": {"key": "x"}, "id": "call_sd1"}
            ],
        ),
        AIMessage(content="Done."),
    ]
    mock_llm = MockChatModel(responses=responses)
    registry = ToolRegistry()
    registry.register(_StateDeltaTool())
    session_mgr = SessionManager(tmp_sessions_dir)
    config = RunnerConfig(max_turns=5, auto_compact=False)
    runner = AgentRunner(
        llm=mock_llm, session_manager=session_mgr, tool_registry=registry, config=config
    )

    session = session_mgr.create_session_sync()
    result = await runner.run(
        session.session_id, "login", user_id="test_user", stream=False
    )

    assert result.response.content == "Done."
    state = session.state
    assert state["auth_token"] == "tok_abc"
    assert state["user:name"] == "Alice"


@pytest.mark.asyncio
async def test_temp_state_stripped_after_run(tmp_sessions_dir: Path) -> None:
    """temp: keys from input_context are available during run but stripped after."""
    responses = [AIMessage(content="ok")]
    runner, _ = _make_runner(tmp_sessions_dir, responses=responses)
    session = runner.session_manager.create_session_sync()

    await runner.run(
        session.session_id,
        "hi",
        user_id="test_user",
        stream=False,
        input_context={"temp:trace_id": "t1", "user:id": "U1"},
    )

    state = session.state
    assert "temp:trace_id" not in state
    assert state["user:id"] == "U1"


# ============ A2UI History Marker Tests ============


class _A2UITool(AgentTool):
    """Tool that returns an A2UI component result."""

    name = "a2ui_tool"
    description = "A tool that renders a UI card"
    parameters = [
        ToolParameter(name="title", type="string", description="Card title"),
    ]

    async def execute(
        self, tool_call: ToolCall, context: dict[str, Any] | None = None
    ) -> AgentToolResult:
        return AgentToolResult.a2ui_result(
            tool_call.id,
            data={"type": "card", "title": "Test Card", "amount": 99999},
        )


def _make_runner_with_a2ui(sessions_dir: Path, responses: list[Any]) -> AgentRunner:
    mock_llm = MockChatModel(responses=responses)
    registry = ToolRegistry()
    registry.register(_A2UITool())
    session_mgr = SessionManager(sessions_dir)
    config = RunnerConfig(max_turns=5, auto_compact=False)
    return AgentRunner(
        llm=mock_llm, session_manager=session_mgr, tool_registry=registry, config=config
    )


@pytest.mark.asyncio
async def test_a2ui_history_marker_is_neutral(tmp_sessions_dir: Path) -> None:
    """A2UI tool result in LLM history must be a neutral JSON marker, not a display-completion sentence."""
    responses = [
        AIMessage(
            content="",
            tool_calls=[
                {"name": "a2ui_tool", "args": {"title": "Plan"}, "id": "call_a2ui_1"}
            ],
        ),
        AIMessage(content="Here is your plan."),
    ]
    runner = _make_runner_with_a2ui(tmp_sessions_dir, responses)
    session = runner.session_manager.create_session_sync()

    await runner.run(
        session.session_id, "Show me a plan", user_id="test_user", stream=False
    )

    # Inspect what _build_messages produces for the A2UI tool result
    state = session.state
    messages = runner._build_messages(session.session_id, state)
    tool_messages = [
        m
        for m in messages
        if m["role"] == "tool" and m.get("tool_call_id") == "call_a2ui_1"
    ]

    assert len(tool_messages) == 1, (
        "Expected exactly one tool message for the A2UI call"
    )
    content = tool_messages[0]["content"]

    assert content.startswith("[已向用户展示卡片")

    # Must NOT leak card payload values
    assert "99999" not in content
    assert "Test Card" not in content


@pytest.mark.asyncio
async def test_a2ui_on_ui_component_still_fires(tmp_sessions_dir: Path) -> None:
    """A2UI result must still trigger on_ui_component so the frontend receives the card."""
    responses = [
        AIMessage(
            content="",
            tool_calls=[
                {"name": "a2ui_tool", "args": {"title": "Plan"}, "id": "call_a2ui_2"}
            ],
        ),
        AIMessage(content="Done."),
    ]
    runner = _make_runner_with_a2ui(tmp_sessions_dir, responses)
    session = runner.session_manager.create_session_sync()

    captured_components: list[dict] = []

    class _Handler:
        def on_step(self, text: str) -> None:
            pass

        def on_content_delta(self, delta: str, turn: int = 1) -> None:
            pass

        def on_tool_call_start(self, tool_call_id: str, name: str, args: Any) -> None:
            pass

        def on_tool_call_result(
            self, tool_call_id: str, name: str, result: Any
        ) -> None:
            pass

        def on_ui_component(self, component: dict) -> None:
            captured_components.append(component)

    await runner.run(
        session.session_id,
        "Show me a plan",
        user_id="test_user",
        stream=False,
        handler=_Handler(),
    )

    assert len(captured_components) == 1, (
        "on_ui_component must be called once for the A2UI tool result"
    )
    assert captured_components[0].get("type") == "card"


@pytest.mark.asyncio
async def test_input_context_seed_only(tmp_sessions_dir: Path) -> None:
    """input_context keys always overwrite session.state (覆盖语义).

    temp: prefixed keys are stripped after run() by strip_temp_state().
    """
    responses = [AIMessage(content="ok")]
    runner, _ = _make_runner(tmp_sessions_dir, responses=responses)
    session = runner.session_manager.create_session_sync(state={"user:id": "existing"})

    await runner.run(
        session.session_id,
        "hi",
        user_id="test_user",
        stream=False,
        input_context={"user:id": "new_value", "temp:x": "t"},
    )

    state = session.state
    assert state["user:id"] == "new_value"
    assert "temp:x" not in state


# ============ A2UI redaction tests ============


@pytest.mark.asyncio
async def test_a2ui_tool_call_args_preserved_in_history(tmp_sessions_dir: Path) -> None:
    """render_a2ui arguments must be preserved (not redacted) so models see valid few-shot examples."""
    blocks_payload = [
        {
            "type": "WithdrawPlanCard",
            "data": {"channels": ["survival_fund"], "target": 10000},
        }
    ]
    runner = _make_runner_with_a2ui(tmp_sessions_dir, responses=[])
    session = runner.session_manager.create_session_sync()

    tc = ToolCall(
        id="call_redact_1",
        name="render_a2ui",
        arguments={"blocks": json.dumps(blocks_payload)},
    )
    session.add_message(AgentMessage.user("取10000"))
    session.add_message(AgentMessage.assistant(content="", tool_calls=[tc]))
    session.add_message(
        AgentMessage.tool(
            [
                AgentToolResult.a2ui_result(
                    "call_redact_1", {"event": "beginRendering", "components": []}
                ),
            ]
        )
    )
    session.add_message(AgentMessage.assistant(content="需要办理吗？"))

    messages = runner._build_messages(session.session_id, session.state)
    assistant_msgs = [
        m for m in messages if m["role"] == "assistant" and m.get("tool_calls")
    ]

    assert len(assistant_msgs) == 1
    tc_out = assistant_msgs[0]["tool_calls"][0]
    assert tc_out["function"]["name"] == "render_a2ui"
    args = json.loads(tc_out["function"]["arguments"])
    assert args["blocks"] == json.dumps(blocks_payload), (
        "render_a2ui arguments must be preserved"
    )
    assert "WithdrawPlanCard" in tc_out["function"]["arguments"]

    tool_msgs = [
        m
        for m in messages
        if m["role"] == "tool" and m["tool_call_id"] == "call_redact_1"
    ]
    assert len(tool_msgs) == 1
    assert tool_msgs[0]["content"].startswith("[已向用户展示卡片"), (
        "A2UI tool result must still be redacted"
    )


@pytest.mark.asyncio
async def test_non_a2ui_tool_call_args_not_redacted(tmp_sessions_dir: Path) -> None:
    """Non-A2UI tool calls must keep their original arguments."""
    runner = _make_runner_with_a2ui(tmp_sessions_dir, responses=[])
    session = runner.session_manager.create_session_sync()

    tc = ToolCall(
        id="call_keep_1", name="mock_tool", arguments={"key": "important_value"}
    )
    session.add_message(AgentMessage.user("do something"))
    session.add_message(AgentMessage.assistant(content="", tool_calls=[tc]))
    session.add_message(
        AgentMessage.tool(
            [
                AgentToolResult.json_result("call_keep_1", {"result": "done"}),
            ]
        )
    )
    session.add_message(AgentMessage.assistant(content="Result."))

    messages = runner._build_messages(session.session_id, session.state)
    assistant_msgs = [
        m for m in messages if m["role"] == "assistant" and m.get("tool_calls")
    ]

    assert len(assistant_msgs) == 1
    tc_out = assistant_msgs[0]["tool_calls"][0]
    args = json.loads(tc_out["function"]["arguments"])
    assert args["key"] == "important_value", "Non-A2UI tool args must not be redacted"


@pytest.mark.asyncio
async def test_a2ui_marker_by_name_not_result_type(tmp_sessions_dir: Path) -> None:
    """A2UI tool result marker must work based on tool call name, not result_type.

    Simulates a disk-reloaded session where result_type=A2UI was lost (deserialized as JSON).
    The name-based check on the tool call must still apply the a2ui_emitted marker.
    """
    runner = _make_runner_with_a2ui(tmp_sessions_dir, responses=[])
    session = runner.session_manager.create_session_sync()

    # Use "render_a2ui" name to match the name-based check in _build_messages
    tc = ToolCall(id="call_name_test", name="render_a2ui", arguments={"blocks": "[]"})
    assistant_msg = AgentMessage.assistant(content="", tool_calls=[tc])
    session.add_message(assistant_msg)

    # Simulate disk-reloaded result: result_type is JSON (not A2UI)
    fake_result = AgentToolResult(
        tool_call_id="call_name_test",
        result_type=ToolResultType.JSON,
        content={
            "event": "beginRendering",
            "surfaceId": "abc",
            "components": [{"id": "x"}],
        },
    )
    tool_msg = AgentMessage.tool([fake_result])
    session.add_message(tool_msg)

    messages = runner._build_messages(session.session_id, session.state)
    tool_messages = [
        m
        for m in messages
        if m["role"] == "tool" and m.get("tool_call_id") == "call_name_test"
    ]

    assert len(tool_messages) == 1
    content = tool_messages[0]["content"]
    assert content.startswith("[已向用户展示卡片"), (
        "Must apply masking based on tool name, even when result_type is JSON"
    )
    assert "beginRendering" not in content
    assert "surfaceId" not in content


class _FakeMemoryManager:
    """Minimal MemoryManager stand-in for mark_memory_dirty tests."""

    def __init__(self) -> None:
        self.dirty_count = 0

    def mark_dirty(self) -> None:
        self.dirty_count += 1

    async def initialize(self) -> None:
        return None

    async def close(self) -> None:
        return None


def test_mark_memory_dirty_noop_without_memory_manager(tmp_sessions_dir: Path) -> None:
    runner, _ = _make_runner(tmp_sessions_dir)
    runner.mark_memory_dirty()


def test_mark_memory_dirty_is_noop_after_redesign(tmp_sessions_dir: Path) -> None:
    """mark_memory_dirty is a no-op after SQLite removal — kept for API compat."""
    mock_llm = MockChatModel(responses=[])
    llm = mock_llm  # type: ignore[arg-type]
    mm = _FakeMemoryManager()
    session_mgr = SessionManager(tmp_sessions_dir)
    runner = AgentRunner(
        llm=llm,
        session_manager=session_mgr,
        memory_manager=mm,  # type: ignore[arg-type]
    )
    runner.mark_memory_dirty()
    assert mm.dirty_count == 0, "mark_memory_dirty should be a no-op (no SQLite index)"
