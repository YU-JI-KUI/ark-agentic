"""Unit tests for ToolExecutor."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from ark_agentic.core.tools.base import AgentTool
from ark_agentic.core.tools.executor import ToolExecutor
from ark_agentic.core.tools.registry import ToolRegistry
from ark_agentic.core.types import (
    AgentToolResult,
    ToolCall,
    ToolLoopAction,
    ToolResultType,
)


class _EchoTool(AgentTool):
    name = "echo"
    description = "echo"
    parameters = []

    async def execute(
        self, tool_call: ToolCall, context: dict | None = None
    ) -> AgentToolResult:
        return AgentToolResult.json_result(tool_call.id, {"echo": tool_call.arguments})


class _StopTool(AgentTool):
    name = "stop_tool"
    description = "stop"
    parameters = []

    async def execute(
        self, tool_call: ToolCall, context: dict | None = None
    ) -> AgentToolResult:
        return AgentToolResult(
            tool_call_id=tool_call.id,
            result_type=ToolResultType.JSON,
            content={},
            loop_action=ToolLoopAction.STOP,
        )


@pytest.mark.asyncio
async def test_executor_unknown_tool_returns_error() -> None:
    reg = ToolRegistry()
    ex = ToolExecutor(reg, timeout=5.0, max_calls_per_turn=5)
    tc = ToolCall.create("missing", {})
    out = await ex.execute([tc], {})
    assert len(out) == 1
    assert out[0].is_error
    assert "not found" in str(out[0].content).lower()


@pytest.mark.asyncio
async def test_executor_respects_max_calls_per_turn() -> None:
    reg = ToolRegistry()
    reg.register(_EchoTool())
    ex = ToolExecutor(reg, timeout=5.0, max_calls_per_turn=2)
    calls = [
        ToolCall.create("echo", {"i": 0}),
        ToolCall.create("echo", {"i": 1}),
        ToolCall.create("echo", {"i": 2}),
    ]
    out = await ex.execute(calls, {})
    assert len(out) == 2


@pytest.mark.asyncio
async def test_executor_state_delta_not_visible_during_parallel_execution() -> None:
    """With parallel execution, same-turn tools can't see each other's state_delta.
    state_delta is merged post-execution at the runner level."""
    reg = ToolRegistry()

    class _DeltaTool(AgentTool):
        name = "delta"
        description = "d"
        parameters = []

        async def execute(
            self, tool_call: ToolCall, context: dict | None = None
        ) -> AgentToolResult:
            return AgentToolResult.json_result(
                tool_call.id,
                {"x": 1},
                metadata={"state_delta": {"user_flag": True}},
            )

    seen: dict[str, bool | None] = {"flag": None}

    class _ReadTool(AgentTool):
        name = "read_flag"
        description = "r"
        parameters = []

        async def execute(
            self, tool_call: ToolCall, context: dict | None = None
        ) -> AgentToolResult:
            seen["flag"] = (context or {}).get("user_flag")
            return AgentToolResult.json_result(tool_call.id, {})

    reg.register(_DeltaTool())
    reg.register(_ReadTool())
    ex = ToolExecutor(reg, timeout=5.0, max_calls_per_turn=5)
    results = await ex.execute(
        [ToolCall.create("delta", {}), ToolCall.create("read_flag", {})],
        {},
    )
    # Parallel: read_flag doesn't see delta's state_delta during execution
    assert seen["flag"] is None
    # But the state_delta is properly returned in the result metadata
    assert results[0].metadata.get("state_delta") == {"user_flag": True}


@pytest.mark.asyncio
async def test_executor_parallel_returns_all_results_including_stop() -> None:
    """With parallel execution, all tools run concurrently. STOP is handled at runner level."""
    reg = ToolRegistry()
    reg.register(_EchoTool())
    reg.register(_StopTool())

    calls = [
        ToolCall.create("stop_tool", {}),
        ToolCall.create("echo", {"n": 1}),
    ]
    ex = ToolExecutor(reg, timeout=5.0, max_calls_per_turn=5)
    out = await ex.execute(calls, {})
    assert len(out) == 2
    assert out[0].loop_action == ToolLoopAction.STOP
    assert out[1].loop_action == ToolLoopAction.CONTINUE


@pytest.mark.asyncio
async def test_executor_records_duration_ms_on_result() -> None:
    """Every tool result carries a per-call latency in metadata."""
    reg = ToolRegistry()
    reg.register(_EchoTool())
    ex = ToolExecutor(reg, timeout=5.0, max_calls_per_turn=5)
    out = await ex.execute([ToolCall.create("echo", {})], {})
    assert "duration_ms" in out[0].metadata
    assert isinstance(out[0].metadata["duration_ms"], int)
    assert out[0].metadata["duration_ms"] >= 0


@pytest.mark.asyncio
async def test_executor_records_owning_skill_when_active() -> None:
    """When ctx carries _active_skill_id, it lands on the result metadata."""
    reg = ToolRegistry()
    reg.register(_EchoTool())
    ex = ToolExecutor(reg, timeout=5.0, max_calls_per_turn=5)
    out = await ex.execute(
        [ToolCall.create("echo", {})],
        {"_active_skill_id": "skill_x"},
    )
    assert out[0].metadata["owning_skill"] == "skill_x"


@pytest.mark.asyncio
async def test_executor_omits_owning_skill_when_none_active() -> None:
    reg = ToolRegistry()
    reg.register(_EchoTool())
    ex = ToolExecutor(reg, timeout=5.0, max_calls_per_turn=5)
    out = await ex.execute([ToolCall.create("echo", {})], {})
    assert "owning_skill" not in out[0].metadata


@pytest.mark.asyncio
async def test_executor_dispatches_events_to_handler() -> None:
    from ark_agentic.core.types import CustomToolEvent

    reg = ToolRegistry()

    class _EvtTool(AgentTool):
        name = "evt"
        description = "e"
        parameters = []

        async def execute(
            self, tool_call: ToolCall, context: dict | None = None
        ) -> AgentToolResult:
            return AgentToolResult(
                tool_call_id=tool_call.id,
                result_type=ToolResultType.JSON,
                content={},
                events=[CustomToolEvent(custom_type="t", payload={"a": 1})],
            )

    reg.register(_EvtTool())
    handler = MagicMock()
    ex = ToolExecutor(reg, timeout=5.0, max_calls_per_turn=5)
    await ex.execute([ToolCall.create("evt", {})], {}, handler=handler)
    handler.on_custom_event.assert_called()
