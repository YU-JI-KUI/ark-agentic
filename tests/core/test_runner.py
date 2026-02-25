"""Tests for AgentRunner core happy paths with ChatOpenAI backend."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from typing import Any, AsyncIterator
import asyncio

from ark_agentic.core.runner import AgentRunner, RunnerConfig, RunResult
from ark_agentic.core.session import SessionManager
from ark_agentic.core.tools.base import AgentTool, ToolParameter
from ark_agentic.core.tools.registry import ToolRegistry
from ark_agentic.core.types import AgentMessage, AgentToolResult, ToolCall, MessageRole
from langchain_core.messages import AIMessage, AIMessageChunk


# ============ Mock Tools ============

class _MockTool(AgentTool):
    """Minimal tool for testing."""

    name = "mock_tool"
    description = "A mock tool for testing"
    parameters = [
        ToolParameter(name="key", type="string", description="A test key"),
    ]

    async def execute(self, tool_call: ToolCall, context: dict[str, Any]) -> AgentToolResult:
        return AgentToolResult(
            tool_call_id=tool_call.id,
            result_type="json",
            content={"result": f"processed_{context.get('input_val', 'default')}"},
        )


# ============ Mock LangChain LLM ============

class MockChatModel:
    """Mocks LangChain ChatOpenAI interface for native compatibility without external calls."""
    
    def __init__(self, responses: list[Any], stream_responses: list[list[Any]] = None):
        self.responses = responses
        self.stream_responses = stream_responses or []
        self.call_count = 0
        self.stream_call_count = 0

    def bind_tools(self, tools: list[dict[str, Any]], **kwargs) -> 'MockChatModel':
        return self

    def model_copy(self, update: dict[str, Any] = None) -> 'MockChatModel':
        return self
        
    async def ainvoke(self, messages: list[Any], **kwargs) -> AIMessage:
        if self.call_count >= len(self.responses):
            raise RuntimeError("ainvoke called more times than responses provided")
        res = self.responses[self.call_count]
        self.call_count += 1
        return res

    async def astream(self, messages: list[Any], **kwargs) -> AsyncIterator[AIMessageChunk]:
        if self.stream_call_count >= len(self.stream_responses):
            raise RuntimeError("astream called more times than stream_responses provided")
        chunks = self.stream_responses[self.stream_call_count]
        self.stream_call_count += 1
        for chunk in chunks:
            yield chunk


# ============ Helpers ============

def _make_runner(
    responses: list[Any] = None,
    stream_responses: list[list[Any]] = None,
    enable_streaming: bool = False
) -> tuple[AgentRunner, _MockTool]:
    """Create a fresh AgentRunner with mock dependencies."""
    mock_llm = MockChatModel(responses=responses or [], stream_responses=stream_responses or [])
    llm = mock_llm  # type: ignore[arg-type]  # duck-typed BaseChatModel for tests
    registry = ToolRegistry()
    tool = _MockTool()
    registry.register(tool)
    session_mgr = SessionManager(enable_persistence=False)
    config = RunnerConfig(
        max_turns=5,
        enable_streaming=enable_streaming,
        auto_compact=False,
    )
    runner = AgentRunner(
        llm=llm,
        tool_registry=registry,
        session_manager=session_mgr,
        config=config,
    )
    return runner, tool


# ============ Tests ============

@pytest.mark.asyncio
async def test_run_basic_text_response() -> None:
    # Arrange
    responses = [
        AIMessage(content="Hello! I am a helpful agent.")
    ]
    runner, _ = _make_runner(responses=responses)
    session = runner.session_manager.create_session_sync()
    
    # Act
    result = await runner.run(session.session_id, "Who are you?")
    
    # Assert
    assert result.response.content == "Hello! I am a helpful agent."
    assert result.turns == 1
    assert result.tool_calls_count == 0


@pytest.mark.asyncio
async def test_run_with_tool_call() -> None:
    # Arrange
    responses = [
        AIMessage(
            content="",
            tool_calls=[{"name": "mock_tool", "args": {"key": "test_key"}, "id": "call_123"}]
        ),
        AIMessage(content="I have processed your request using the tool.")
    ]
    runner, _ = _make_runner(responses=responses)
    session = runner.session_manager.create_session_sync()
    
    # Act
    result = await runner.run(session.session_id, "Use the tool!", input_context={"input_val": "123"})
    
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
async def test_run_streaming_text_response() -> None:
    # Arrange
    stream_responses = [
        [
            AIMessageChunk(content="Hello"),
            AIMessageChunk(content=" World"),
            AIMessageChunk(content="!")
        ]
    ]
    runner, _ = _make_runner(stream_responses=stream_responses, enable_streaming=True)
    session = runner.session_manager.create_session_sync()
    
    captured_deltas = []
    
    class MockHandler:
        def on_content_delta(self, delta: str, turn: int = 1) -> None:
            captured_deltas.append(delta)

        def on_tool_call_start(self, tool_call_id: str, name: str, args: str) -> None:
            pass

        def on_tool_call_result(self, tool_call_id: str, name: str, result: str) -> None:
            pass

        def on_step(self, status: str) -> None:
            pass

        def on_ui_component(self, component: dict) -> None:
            pass

    # Act
    result = await runner.run(session.session_id, "Greeting", handler=MockHandler())
    
    # Assert

    assert result.response.content == "Hello World!"
    assert result.turns == 1
    assert captured_deltas == ["Hello", " World", "!"]


@pytest.mark.asyncio
async def test_run_streaming_with_tool_call() -> None:
    # Arrange
    stream_responses = [
        # Turn 1: Steaming tool call chunk
        [
            AIMessageChunk(
                content="", 
                tool_call_chunks=[{"name": "mock_tool", "args": "{\"key\": \"test\"}", "id": "call_abc", "index": 0}]
            )
        ],
        # Turn 2: Steaming final answer
        [
            AIMessageChunk(content="Done "),
            AIMessageChunk(content="processing.")
        ]
    ]
    runner, _ = _make_runner(stream_responses=stream_responses, enable_streaming=True)
    session = runner.session_manager.create_session_sync()
    
    captured_deltas = []
    captured_tool_starts = []
    captured_steps = []
    
    class MockHandler:
        def on_content_delta(self, delta: str, turn: int = 1) -> None:
            captured_deltas.append(delta)

        def on_tool_call_start(self, tool_call_id: str, name: str, args: str) -> None:
            captured_tool_starts.append(name)

        def on_tool_call_result(self, tool_call_id: str, name: str, result: str) -> None:
            pass

        def on_step(self, status: str) -> None:
            captured_steps.append(status)

        def on_ui_component(self, component: dict) -> None:
            pass

    # Act
    result = await runner.run(session.session_id, "Use tool", handler=MockHandler(), input_context={"input_val": "abc"})
    
    # Assert

    assert result.response.content == "Done processing."
    assert result.turns == 2
    assert result.tool_calls_count == 1
    
    assert captured_deltas == ["Done ", "processing."]
    assert captured_tool_starts == ["mock_tool"]
    # Verify on_step was called
    assert len(captured_steps) > 0


# ============ State Mechanism Tests ============


class _StateDeltaTool(AgentTool):
    """Tool that writes state_delta in result metadata."""

    name = "state_delta_tool"
    description = "A tool that returns state_delta"
    parameters = [
        ToolParameter(name="key", type="string", description="ignored"),
    ]

    async def execute(self, tool_call: ToolCall, context: dict[str, Any] | None = None) -> AgentToolResult:
        return AgentToolResult(
            tool_call_id=tool_call.id,
            result_type="json",
            content={"ok": True},
            metadata={"state_delta": {"auth_token": "tok_abc", "user:name": "Alice"}},
        )


@pytest.mark.asyncio
async def test_state_delta_merge() -> None:
    """Tool's state_delta is merged into session.state and visible in next turn."""
    responses = [
        AIMessage(
            content="",
            tool_calls=[{"name": "state_delta_tool", "args": {"key": "x"}, "id": "call_sd1"}],
        ),
        AIMessage(content="Done."),
    ]
    mock_llm = MockChatModel(responses=responses)
    registry = ToolRegistry()
    registry.register(_StateDeltaTool())
    session_mgr = SessionManager(enable_persistence=False)
    config = RunnerConfig(max_turns=5, enable_streaming=False, auto_compact=False)
    runner = AgentRunner(llm=mock_llm, tool_registry=registry, session_manager=session_mgr, config=config)

    session = session_mgr.create_session_sync()
    result = await runner.run(session.session_id, "login")

    assert result.response.content == "Done."
    state = session.state
    assert state["auth_token"] == "tok_abc"
    assert state["user:name"] == "Alice"


@pytest.mark.asyncio
async def test_temp_state_stripped_after_run() -> None:
    """temp: keys from input_context are available during run but stripped after."""
    responses = [AIMessage(content="ok")]
    runner, _ = _make_runner(responses=responses)
    session = runner.session_manager.create_session_sync()

    await runner.run(
        session.session_id,
        "hi",
        input_context={"temp:trace_id": "t1", "user:id": "U1"},
    )

    state = session.state
    assert "temp:trace_id" not in state
    assert state["user:id"] == "U1"


@pytest.mark.asyncio
async def test_input_context_seed_only() -> None:
    """Non-temp input_context keys seed state only if not present (no overwrite)."""
    responses = [AIMessage(content="ok")]
    runner, _ = _make_runner(responses=responses)
    session = runner.session_manager.create_session_sync(state={"user:id": "existing"})

    await runner.run(
        session.session_id,
        "hi",
        input_context={"user:id": "new_value", "temp:x": "t"},
    )

    state = session.state
    assert state["user:id"] == "existing"
    assert "temp:x" not in state
