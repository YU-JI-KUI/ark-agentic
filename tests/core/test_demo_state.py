"""Tests for demo state tools (SetStateDemoTool, GetStateDemoTool)."""

from __future__ import annotations

import pytest

from ark_agentic.core.tools.demo_state import SetStateDemoTool, GetStateDemoTool
from ark_agentic.core.tools.registry import ToolRegistry
from ark_agentic.core.types import ToolCall


@pytest.fixture
def set_tool() -> SetStateDemoTool:
    return SetStateDemoTool()


@pytest.fixture
def get_tool() -> GetStateDemoTool:
    return GetStateDemoTool()


class TestSetStateDemoTool:
    def test_schema(self) -> None:
        tool = SetStateDemoTool()
        schema = tool.get_json_schema()
        assert schema["function"]["name"] == "demo_set_state"
        assert "key" in schema["function"]["parameters"]["properties"]
        assert "value" in schema["function"]["parameters"]["properties"]

    @pytest.mark.asyncio
    async def test_set_returns_state_delta(self, set_tool: SetStateDemoTool) -> None:
        tc = ToolCall(id="tc1", name="demo_set_state", arguments={"key": "foo", "value": "bar"})
        result = await set_tool.execute(tc, {})
        assert result.metadata.get("state_delta") == {"foo": "bar"}
        assert result.content.get("ok") is True
        assert result.content.get("key") == "foo"

    @pytest.mark.asyncio
    async def test_set_empty_key_errors(self, set_tool: SetStateDemoTool) -> None:
        tc = ToolCall(id="tc1", name="demo_set_state", arguments={"key": "", "value": "x"})
        result = await set_tool.execute(tc, {})
        assert result.is_error


class TestGetStateDemoTool:
    def test_schema(self) -> None:
        tool = GetStateDemoTool()
        schema = tool.get_json_schema()
        assert schema["function"]["name"] == "demo_get_state"
        assert "key" in schema["function"]["parameters"]["properties"]

    @pytest.mark.asyncio
    async def test_get_found(self, get_tool: GetStateDemoTool) -> None:
        tc = ToolCall(id="tc1", name="demo_get_state", arguments={"key": "foo"})
        result = await get_tool.execute(tc, {"foo": "bar", "session_id": "s1"})
        assert result.content.get("found") is True
        assert result.content.get("key") == "foo"
        assert result.content.get("value") == "bar"

    @pytest.mark.asyncio
    async def test_get_not_found(self, get_tool: GetStateDemoTool) -> None:
        tc = ToolCall(id="tc1", name="demo_get_state", arguments={"key": "missing"})
        result = await get_tool.execute(tc, {"session_id": "s1"})
        assert result.content.get("found") is False
        assert "missing" in result.content.get("message", "")

    @pytest.mark.asyncio
    async def test_get_empty_key_errors(self, get_tool: GetStateDemoTool) -> None:
        tc = ToolCall(id="tc1", name="demo_get_state", arguments={"key": ""})
        result = await get_tool.execute(tc, {})
        assert result.is_error


@pytest.mark.asyncio
async def test_set_then_get_via_context() -> None:
    """Integration: set writes state_delta; caller merges into context; get reads from context."""
    set_tool = SetStateDemoTool()
    get_tool = GetStateDemoTool()
    context: dict[str, str] = {}

    tc_set = ToolCall(id="tc_set", name="demo_set_state", arguments={"key": "selected_plan", "value": "plan_a"})
    result_set = await set_tool.execute(tc_set, context)
    assert "state_delta" in result_set.metadata
    context.update(result_set.metadata["state_delta"])

    tc_get = ToolCall(id="tc_get", name="demo_get_state", arguments={"key": "selected_plan"})
    result_get = await get_tool.execute(tc_get, context)
    assert result_get.content.get("found") is True
    assert result_get.content.get("value") == "plan_a"
