"""Tests for ToolExecutor parallel execution (asyncio.gather)."""

from __future__ import annotations

import asyncio
import time

import pytest

from ark_agentic.core.tools.base import AgentTool
from ark_agentic.core.tools.executor import ToolExecutor
from ark_agentic.core.tools.registry import ToolRegistry
from ark_agentic.core.types import AgentToolResult, ToolCall, ToolLoopAction, ToolResultType


class _SlowTool(AgentTool):
    name = "slow"
    description = "takes some time"
    parameters = []

    async def execute(self, tool_call: ToolCall, context: dict | None = None) -> AgentToolResult:
        await asyncio.sleep(0.1)
        return AgentToolResult.json_result(tool_call.id, {"done": True})


class _StateDeltaTool(AgentTool):
    name = "set_state"
    description = "sets state delta"
    parameters = []

    async def execute(self, tool_call: ToolCall, context: dict | None = None) -> AgentToolResult:
        key = (tool_call.arguments or {}).get("key", "default")
        val = (tool_call.arguments or {}).get("val", "v")
        return AgentToolResult.json_result(
            tool_call.id, {"key": key},
            metadata={"state_delta": {key: val}},
        )


@pytest.mark.asyncio
async def test_parallel_execution_is_concurrent() -> None:
    """Three 100ms tools should finish in ~100ms, not ~300ms."""
    reg = ToolRegistry()
    reg.register(_SlowTool())
    ex = ToolExecutor(reg, timeout=5.0, max_calls_per_turn=5)

    calls = [ToolCall.create("slow", {}) for _ in range(3)]
    start = time.monotonic()
    results = await ex.execute(calls, {})
    elapsed = time.monotonic() - start

    assert len(results) == 3
    assert all(not r.is_error for r in results)
    assert elapsed < 0.25, f"Expected ~100ms parallel, got {elapsed*1000:.0f}ms"


@pytest.mark.asyncio
async def test_parallel_state_delta_merged_in_order() -> None:
    """state_delta from multiple tools merged sequentially after parallel execution."""
    reg = ToolRegistry()
    reg.register(_StateDeltaTool())
    ex = ToolExecutor(reg, timeout=5.0, max_calls_per_turn=5)

    calls = [
        ToolCall.create("set_state", {"key": "a", "val": "1"}),
        ToolCall.create("set_state", {"key": "b", "val": "2"}),
        ToolCall.create("set_state", {"key": "c", "val": "3"}),
    ]
    results = await ex.execute(calls, {})

    assert len(results) == 3
    deltas = [r.metadata.get("state_delta", {}) for r in results]
    assert deltas[0] == {"a": "1"}
    assert deltas[1] == {"b": "2"}
    assert deltas[2] == {"c": "3"}


@pytest.mark.asyncio
async def test_parallel_context_isolation() -> None:
    """Each parallel coroutine gets a snapshot of ctx, not a shared reference."""
    observed: list[dict] = []

    class _ObserveTool(AgentTool):
        name = "observe"
        description = "captures context snapshot"
        parameters = []

        async def execute(self, tool_call: ToolCall, context: dict | None = None) -> AgentToolResult:
            observed.append(dict(context or {}))
            await asyncio.sleep(0.01)
            return AgentToolResult.json_result(tool_call.id, {})

    reg = ToolRegistry()
    reg.register(_ObserveTool())
    ex = ToolExecutor(reg, timeout=5.0, max_calls_per_turn=5)

    initial_ctx = {"shared_key": "shared_val"}
    calls = [ToolCall.create("observe", {}) for _ in range(3)]
    await ex.execute(calls, initial_ctx)

    assert len(observed) == 3
    for ctx_snapshot in observed:
        assert ctx_snapshot["shared_key"] == "shared_val"


@pytest.mark.asyncio
async def test_parallel_error_in_one_tool_doesnt_block_others() -> None:
    """One failing tool shouldn't prevent other parallel tools from completing."""

    class _FailTool(AgentTool):
        name = "fail"
        description = "always fails"
        parameters = []

        async def execute(self, tool_call: ToolCall, context: dict | None = None) -> AgentToolResult:
            raise RuntimeError("intentional failure")

    class _OkTool(AgentTool):
        name = "ok"
        description = "ok"
        parameters = []

        async def execute(self, tool_call: ToolCall, context: dict | None = None) -> AgentToolResult:
            return AgentToolResult.json_result(tool_call.id, {"ok": True})

    reg = ToolRegistry()
    reg.register(_FailTool())
    reg.register(_OkTool())
    ex = ToolExecutor(reg, timeout=5.0, max_calls_per_turn=5)

    calls = [
        ToolCall.create("fail", {}),
        ToolCall.create("ok", {}),
    ]
    results = await ex.execute(calls, {})

    assert len(results) == 2
    assert results[0].is_error
    assert "intentional failure" in str(results[0].content)
    assert not results[1].is_error
    assert results[1].content == {"ok": True}


