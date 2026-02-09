"""Tests for AgentRunner callback isolation and concurrency safety.

Verifies that the race condition fixed by passing on_step/on_content as
run() parameters (instead of shared instance state) works correctly.
"""

from __future__ import annotations

import asyncio
import warnings
from typing import Any, AsyncIterator
from unittest.mock import MagicMock

import pytest

from ark_agentic.core.runner import AgentRunner, RunnerConfig, RunResult
from ark_agentic.core.session import SessionManager
from ark_agentic.core.tools.base import AgentTool, ToolParameter
from ark_agentic.core.tools.registry import ToolRegistry
from ark_agentic.core.types import AgentMessage, AgentToolResult, ToolCall


# ============ Mock LLM Client ============


class _MockStreamChunk:
    """Helper to build OpenAI-compatible SSE chunks."""

    @staticmethod
    def content_delta(text: str) -> dict[str, Any]:
        return {"choices": [{"delta": {"content": text}, "finish_reason": None}]}

    @staticmethod
    def tool_start(tool_id: str, name: str) -> dict[str, Any]:
        return {
            "choices": [{
                "delta": {
                    "tool_calls": [{
                        "index": 0,
                        "id": tool_id,
                        "function": {"name": name},
                    }]
                },
                "finish_reason": None,
            }]
        }

    @staticmethod
    def tool_args(args: str) -> dict[str, Any]:
        return {
            "choices": [{
                "delta": {
                    "tool_calls": [{
                        "index": 0,
                        "function": {"arguments": args},
                    }]
                },
                "finish_reason": None,
            }]
        }

    @staticmethod
    def finish(reason: str = "stop") -> dict[str, Any]:
        return {
            "choices": [{"delta": {}, "finish_reason": reason}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }


class MockLLMClient:
    """Mock LLM that returns tool calls on turn 1, text answer on turn 2.

    Supports streaming by yielding SSE chunks.  A configurable delay between
    chunks lets us simulate realistic async scheduling for concurrency tests.
    """

    def __init__(self, answer_text: str = "Final answer", delay: float = 0.0) -> None:
        self._answer_text = answer_text
        self._delay = delay
        self._call_count = 0

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        stream: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any] | AsyncIterator[dict[str, Any]]:
        self._call_count += 1

        has_tool_results = any(m.get("role") == "tool" for m in messages)

        if stream:
            return self._stream(has_tool_results)
        else:
            return self._non_stream(has_tool_results)

    def _non_stream(self, has_tool_results: bool) -> dict[str, Any]:
        if not has_tool_results:
            # Turn 1: return tool calls
            return {
                "choices": [{
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [{
                            "id": "call_mock",
                            "type": "function",
                            "function": {
                                "name": "mock_tool",
                                "arguments": '{"key": "value"}',
                            },
                        }],
                    },
                    "finish_reason": "tool_calls",
                }],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            }
        else:
            # Turn 2: return final answer
            return {
                "choices": [{
                    "message": {"role": "assistant", "content": self._answer_text},
                    "finish_reason": "stop",
                }],
                "usage": {"prompt_tokens": 20, "completion_tokens": 10},
            }

    async def _stream(self, has_tool_results: bool) -> AsyncIterator[dict[str, Any]]:
        if not has_tool_results:
            # Turn 1: stream tool call
            for chunk in [
                _MockStreamChunk.tool_start("call_mock", "mock_tool"),
                _MockStreamChunk.tool_args('{"key":'),
                _MockStreamChunk.tool_args('"value"}'),
                _MockStreamChunk.finish("tool_calls"),
            ]:
                if self._delay:
                    await asyncio.sleep(self._delay)
                yield chunk
        else:
            # Turn 2: stream final answer word by word
            words = self._answer_text.split()
            for i, word in enumerate(words):
                delta = word if i == 0 else f" {word}"
                if self._delay:
                    await asyncio.sleep(self._delay)
                yield _MockStreamChunk.content_delta(delta)
            yield _MockStreamChunk.finish("stop")


# ============ Mock Tool ============


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
            content={"result": "mock_value"},
        )


# ============ Helpers ============


def _make_runner(answer: str = "Final answer", delay: float = 0.0) -> AgentRunner:
    """Create a fresh AgentRunner with mock dependencies."""
    llm = MockLLMClient(answer_text=answer, delay=delay)
    registry = ToolRegistry()
    registry.register(_MockTool())
    session_mgr = SessionManager(enable_persistence=False)
    config = RunnerConfig(
        max_turns=5,
        enable_streaming=False,
        auto_compact=False,
        enable_output_validation=False,
    )
    return AgentRunner(
        llm_client=llm,
        tool_registry=registry,
        session_manager=session_mgr,
        config=config,
    )


# ============ Tests ============


class TestRunWithoutCallbacks:
    """run() without on_step/on_content still works (backward compat)."""

    @pytest.mark.asyncio
    async def test_basic_run_no_callbacks(self) -> None:
        runner = _make_runner(answer="Hello world")
        session = runner.session_manager.create_session_sync()
        sid = session.session_id

        result = await runner.run(sid, "test input")

        assert result.response.content == "Hello world"
        assert result.turns == 2  # tool call turn + answer turn
        assert result.tool_calls_count == 1


class TestCallbacksViaRunParams:
    """on_step/on_content passed to run() are used correctly."""

    @pytest.mark.asyncio
    async def test_on_step_receives_tool_status(self) -> None:
        runner = _make_runner()
        session = runner.session_manager.create_session_sync()
        sid = session.session_id

        steps: list[str] = []
        result = await runner.run(
            sid, "test", on_step=lambda s: steps.append(s),
        )

        assert result.response.content is not None
        # Should have at least the tool status and the "信息收集完毕" step
        assert any("mock_tool" in s or "正在处理" in s for s in steps)
        assert any("信息收集完毕" in s for s in steps)

    @pytest.mark.asyncio
    async def test_on_content_receives_streaming_deltas(self) -> None:
        runner = _make_runner(answer="streaming test output")
        runner.config.enable_streaming = True
        session = runner.session_manager.create_session_sync()
        sid = session.session_id

        deltas: list[tuple[str, int]] = []
        result = await runner.run(
            sid,
            "test",
            stream_override=True,
            on_content=lambda d, idx: deltas.append((d, idx)),
        )

        assert result.response.content is not None
        # Deltas should have been collected
        assert len(deltas) > 0
        # All deltas from the final answer should have output_index == 1
        # (index 0 was the tool-call turn, index 1 is the summary turn)
        assert all(idx == 1 for _, idx in deltas)
        # Concatenated deltas should form the answer
        full = "".join(d for d, _ in deltas)
        assert full == "streaming test output"


class TestCallbacksOverrideSetCallbacks:
    """run(on_content=X) takes precedence over set_callbacks(on_content=Y)."""

    @pytest.mark.asyncio
    async def test_run_params_win(self) -> None:
        runner = _make_runner(answer="override test")
        runner.config.enable_streaming = True
        session = runner.session_manager.create_session_sync()
        sid = session.session_id

        legacy_deltas: list[str] = []
        run_deltas: list[str] = []

        # Set legacy callbacks (should trigger deprecation warning)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            runner.set_callbacks(
                on_content=lambda d, idx: legacy_deltas.append(d),
            )

        # Pass per-run callbacks — these should take precedence
        await runner.run(
            sid,
            "test",
            stream_override=True,
            on_content=lambda d, idx: run_deltas.append(d),
        )

        # run() param callback received content
        assert len(run_deltas) > 0
        # Legacy callback received nothing (overridden)
        assert len(legacy_deltas) == 0


class TestSetCallbacksDeprecation:
    """set_callbacks() emits DeprecationWarning."""

    def test_deprecation_warning(self) -> None:
        runner = _make_runner()
        with pytest.warns(DeprecationWarning, match="not safe for concurrent use"):
            runner.set_callbacks(on_step=lambda s: None)


class TestConcurrentRunsIsolation:
    """Two concurrent run() calls with different callbacks are isolated."""

    @pytest.mark.asyncio
    async def test_concurrent_callbacks_do_not_cross(self) -> None:
        """Launch two concurrent runs on the SAME AgentRunner instance.
        Each has its own on_content callback writing to a separate list.
        Verify no cross-contamination."""

        runner = _make_runner(answer="shared answer", delay=0.01)
        runner.config.enable_streaming = True

        # Create two separate sessions
        s1 = runner.session_manager.create_session_sync().session_id
        s2 = runner.session_manager.create_session_sync().session_id

        deltas_a: list[tuple[str, int]] = []
        deltas_b: list[tuple[str, int]] = []
        steps_a: list[str] = []
        steps_b: list[str] = []

        task_a = asyncio.create_task(runner.run(
            s1, "request A",
            stream_override=True,
            on_step=lambda s: steps_a.append(s),
            on_content=lambda d, idx: deltas_a.append((d, idx)),
        ))
        task_b = asyncio.create_task(runner.run(
            s2, "request B",
            stream_override=True,
            on_step=lambda s: steps_b.append(s),
            on_content=lambda d, idx: deltas_b.append((d, idx)),
        ))

        result_a, result_b = await asyncio.gather(task_a, task_b)

        # Both runs should complete successfully
        assert result_a.response.content is not None
        assert result_b.response.content is not None

        # Both collected deltas
        assert len(deltas_a) > 0
        assert len(deltas_b) > 0

        # Both collected steps
        assert len(steps_a) > 0
        assert len(steps_b) > 0

        # The key invariant: neither list is empty and the content
        # came from the correct callback (no cross-contamination).
        # Since both use the same mock LLM answer, we verify by
        # checking the concatenated text matches the expected answer.
        text_a = "".join(d for d, _ in deltas_a)
        text_b = "".join(d for d, _ in deltas_b)
        assert text_a == "shared answer"
        assert text_b == "shared answer"
