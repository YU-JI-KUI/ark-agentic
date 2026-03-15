"""Tests for memory tools (memory_search, memory_get)."""

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ark_agentic.core.tools.memory import (
    MemorySearchTool,
    MemoryGetTool,
    create_memory_tools,
    MemoryProvider,
)
from ark_agentic.core.types import ToolCall


@dataclass
class MockMemorySearchResult:
    path: str
    start_line: int
    end_line: int
    score: float
    snippet: str
    citation: str | None = None


@dataclass
class MockMemoryConfig:
    workspace_dir: str = ""
    index_dir: str = ""


class MockMemoryManager:
    def __init__(self, workspace_dir: str = "") -> None:
        self.config = MockMemoryConfig(workspace_dir=workspace_dir)
        self._initialized = True
        self.search = AsyncMock(return_value=[])

    async def initialize(self) -> None:
        self._initialized = True


TEST_CONTEXT = {"user:id": "test_user"}


def _make_provider(manager: MockMemoryManager) -> MemoryProvider:
    return lambda user_id: manager


class TestMemorySearchTool:
    def test_tool_metadata(self) -> None:
        tool = MemorySearchTool(_make_provider(MockMemoryManager()))
        assert tool.name == "memory_search"
        assert "MEMORY.md" in tool.description
        assert len(tool.parameters) == 3

    def test_get_json_schema(self) -> None:
        tool = MemorySearchTool(_make_provider(MockMemoryManager()))
        schema = tool.get_json_schema()

        assert schema["type"] == "function"
        func = schema["function"]
        assert func["name"] == "memory_search"
        assert "query" in func["parameters"]["properties"]
        assert "max_results" in func["parameters"]["properties"]
        assert "min_score" in func["parameters"]["properties"]

    @pytest.mark.asyncio
    async def test_search_success(self) -> None:
        manager = MockMemoryManager()
        manager.search.return_value = [
            MockMemorySearchResult(
                path="MEMORY.md",
                start_line=10,
                end_line=15,
                score=0.85,
                snippet="Some relevant content",
                citation="MEMORY.md#L10-15",
            )
        ]
        tool = MemorySearchTool(_make_provider(manager))
        call = ToolCall(id="call_1", name="memory_search", arguments={"query": "test"})

        result = await tool.execute(call, TEST_CONTEXT)

        assert result.tool_call_id == "call_1"
        content = result.content
        assert content["query"] == "test"
        assert content["total"] == 1
        assert len(content["results"]) == 1
        assert content["results"][0]["path"] == "MEMORY.md"
        assert content["results"][0]["score"] == 0.85

    @pytest.mark.asyncio
    async def test_search_empty_query(self) -> None:
        tool = MemorySearchTool(_make_provider(MockMemoryManager()))
        call = ToolCall(id="call_1", name="memory_search", arguments={"query": ""})

        result = await tool.execute(call, TEST_CONTEXT)

        assert "error" in result.content
        assert result.content["results"] == []

    @pytest.mark.asyncio
    async def test_search_no_query(self) -> None:
        tool = MemorySearchTool(_make_provider(MockMemoryManager()))
        call = ToolCall(id="call_1", name="memory_search", arguments={})

        result = await tool.execute(call, TEST_CONTEXT)

        assert "error" in result.content

    @pytest.mark.asyncio
    async def test_search_with_params(self) -> None:
        manager = MockMemoryManager()
        manager.search.return_value = []
        tool = MemorySearchTool(_make_provider(manager))
        call = ToolCall(
            id="call_1",
            name="memory_search",
            arguments={"query": "test", "max_results": 10, "min_score": 0.5},
        )

        await tool.execute(call, TEST_CONTEXT)

        manager.search.assert_called_once_with(
            query="test", max_results=10, min_score=0.5
        )

    @pytest.mark.asyncio
    async def test_search_uses_defaults(self) -> None:
        manager = MockMemoryManager()
        manager.search.return_value = []
        tool = MemorySearchTool(_make_provider(manager))
        call = ToolCall(id="call_1", name="memory_search", arguments={"query": "test"})

        await tool.execute(call, TEST_CONTEXT)

        manager.search.assert_called_once_with(query="test", max_results=6, min_score=0.35)

    @pytest.mark.asyncio
    async def test_search_initializes_if_needed(self) -> None:
        manager = MockMemoryManager()
        manager._initialized = False
        manager.initialize = AsyncMock()
        manager.search.return_value = []
        tool = MemorySearchTool(_make_provider(manager))
        call = ToolCall(id="call_1", name="memory_search", arguments={"query": "test"})

        await tool.execute(call, TEST_CONTEXT)

        manager.initialize.assert_called_once()

    @pytest.mark.asyncio
    async def test_search_handles_error(self) -> None:
        manager = MockMemoryManager()
        manager.search.side_effect = Exception("Search failed")
        tool = MemorySearchTool(_make_provider(manager))
        call = ToolCall(id="call_1", name="memory_search", arguments={"query": "test"})

        result = await tool.execute(call, TEST_CONTEXT)

        assert "error" in result.content
        assert "Search failed" in result.content["error"]
        assert result.content["results"] == []

    @pytest.mark.asyncio
    async def test_search_missing_user_id(self) -> None:
        tool = MemorySearchTool(_make_provider(MockMemoryManager()))
        call = ToolCall(id="call_1", name="memory_search", arguments={"query": "test"})

        result = await tool.execute(call, {})

        assert "error" in result.content
        assert "user:id" in result.content["error"]


class TestMemoryGetTool:
    def test_tool_metadata(self) -> None:
        tool = MemoryGetTool(_make_provider(MockMemoryManager()))
        assert tool.name == "memory_get"
        assert "memory file" in tool.description
        assert len(tool.parameters) == 3

    def test_get_json_schema(self) -> None:
        tool = MemoryGetTool(_make_provider(MockMemoryManager()))
        schema = tool.get_json_schema()

        assert schema["type"] == "function"
        func = schema["function"]
        assert func["name"] == "memory_get"
        assert "path" in func["parameters"]["properties"]
        assert "from_line" in func["parameters"]["properties"]
        assert "lines" in func["parameters"]["properties"]

    @pytest.mark.asyncio
    async def test_get_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "MEMORY.md"
            test_content = "\n".join([f"Line {i}" for i in range(1, 11)])
            test_file.write_text(test_content)

            manager = MockMemoryManager(workspace_dir=tmpdir)
            tool = MemoryGetTool(_make_provider(manager))
            call = ToolCall(
                id="call_1", name="memory_get", arguments={"path": "MEMORY.md"}
            )

            result = await tool.execute(call, TEST_CONTEXT)

            assert result.tool_call_id == "call_1"
            content = result.content
            assert content["path"] == "MEMORY.md"
            assert content["from_line"] == 1
            assert content["total_lines"] == 10
            assert "Line 1" in content["text"]

    @pytest.mark.asyncio
    async def test_get_with_range(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "MEMORY.md"
            test_content = "\n".join([f"Line {i}" for i in range(1, 101)])
            test_file.write_text(test_content)

            manager = MockMemoryManager(workspace_dir=tmpdir)
            tool = MemoryGetTool(_make_provider(manager))
            call = ToolCall(
                id="call_1",
                name="memory_get",
                arguments={"path": "MEMORY.md", "from_line": 10, "lines": 5},
            )

            result = await tool.execute(call, TEST_CONTEXT)

            content = result.content
            assert content["from_line"] == 10
            assert content["to_line"] == 14
            assert "Line 10" in content["text"]
            assert "Line 14" in content["text"]
            assert "Line 15" not in content["text"]

    @pytest.mark.asyncio
    async def test_get_empty_path(self) -> None:
        tool = MemoryGetTool(_make_provider(MockMemoryManager()))
        call = ToolCall(id="call_1", name="memory_get", arguments={"path": ""})

        result = await tool.execute(call, TEST_CONTEXT)

        assert "error" in result.content
        assert "Path is required" in result.content["error"]

    @pytest.mark.asyncio
    async def test_get_file_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = MockMemoryManager(workspace_dir=tmpdir)
            tool = MemoryGetTool(_make_provider(manager))
            call = ToolCall(
                id="call_1", name="memory_get", arguments={"path": "nonexistent.md"}
            )

            result = await tool.execute(call, TEST_CONTEXT)

            assert "error" in result.content
            assert "File not found" in result.content["error"]

    @pytest.mark.asyncio
    async def test_get_limits_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "MEMORY.md"
            test_content = "\n".join([f"Line {i}" for i in range(1, 501)])
            test_file.write_text(test_content)

            manager = MockMemoryManager(workspace_dir=tmpdir)
            tool = MemoryGetTool(_make_provider(manager))
            call = ToolCall(
                id="call_1",
                name="memory_get",
                arguments={"path": "MEMORY.md", "lines": 500},
            )

            result = await tool.execute(call, TEST_CONTEXT)

            content = result.content
            assert content["to_line"] <= 200

    @pytest.mark.asyncio
    async def test_get_nested_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            subdir = Path(tmpdir) / "memory"
            subdir.mkdir()
            test_file = subdir / "project.md"
            test_file.write_text("Project memory content")

            manager = MockMemoryManager(workspace_dir=tmpdir)
            tool = MemoryGetTool(_make_provider(manager))
            call = ToolCall(
                id="call_1",
                name="memory_get",
                arguments={"path": "memory/project.md"},
            )

            result = await tool.execute(call, TEST_CONTEXT)

            assert "error" not in result.content or result.content.get("error") is None
            assert "Project memory content" in result.content["text"]


class TestCreateMemoryTools:
    def test_creates_all_tools(self) -> None:
        provider = _make_provider(MockMemoryManager())
        tools = create_memory_tools(provider)

        assert len(tools) == 4
        names = [t.name for t in tools]
        assert "memory_search" in names
        assert "memory_get" in names
        assert "memory_set" in names
        assert "profile_set" in names

    def test_tools_share_provider(self) -> None:
        provider = _make_provider(MockMemoryManager())
        tools = create_memory_tools(provider)

        search_tool = next(t for t in tools if t.name == "memory_search")
        get_tool = next(t for t in tools if t.name == "memory_get")

        assert search_tool._provider is provider
        assert get_tool._provider is provider
