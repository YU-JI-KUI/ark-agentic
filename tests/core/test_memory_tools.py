"""Tests for memory tools (memory_search, memory_get, memory_write)."""

from dataclasses import dataclass
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

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
class MockChunk:
    """Minimal chunk for MemoryGetTool (DB get_chunks_by_location)."""
    start_line: int
    end_line: int
    text: str


@dataclass
class MockMemoryConfig:
    workspace_dir: str = ""
    index_dir: str = ""


class MockMemoryManager:
    def __init__(self, workspace_dir: str = "") -> None:
        self.config = MockMemoryConfig(workspace_dir=workspace_dir)
        self._initialized = True
        self._dirty = False
        self.search = AsyncMock(return_value=[])
        self._store = MagicMock()

    async def initialize(self) -> None:
        self._initialized = True

    def mark_dirty(self) -> None:
        self._dirty = True


TEST_CONTEXT = {"user:id": "test_user"}


def _make_provider(manager: MockMemoryManager) -> MemoryProvider:
    return lambda user_id: manager


class TestMemorySearchTool:
    def test_tool_metadata(self) -> None:
        tool = MemorySearchTool(_make_provider(MockMemoryManager()))
        assert tool.name == "memory_search"
        assert "语义搜索" in tool.description
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
        assert "MEMORY.md" in tool.description or "记忆" in tool.description
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
        manager = MockMemoryManager()
        manager._store.get_chunks_by_location.return_value = [
            MockChunk(start_line=1, end_line=10, text="Line 1\nLine 2\n...\nLine 10"),
        ]
        tool = MemoryGetTool(_make_provider(manager))
        call = ToolCall(
            id="call_1", name="memory_get", arguments={"path": "MEMORY.md"}
        )

        result = await tool.execute(call, TEST_CONTEXT)

        assert result.tool_call_id == "call_1"
        content = result.content
        assert content["path"] == "MEMORY.md"
        assert content["from_line"] == 1
        assert content["to_line"] == 10
        assert content["total_chunks"] == 1
        assert "Line 1" in content["text"]

    @pytest.mark.asyncio
    async def test_get_with_range(self) -> None:
        manager = MockMemoryManager()
        manager._store.get_chunks_by_location.return_value = [
            MockChunk(start_line=10, end_line=14, text="Line 10\nLine 11\nLine 12\nLine 13\nLine 14"),
        ]
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
        manager._store.get_chunks_by_location.assert_called_once()
        call_kw = manager._store.get_chunks_by_location.call_args[1]
        assert call_kw["from_line"] == 10
        assert call_kw["limit"] == 5

    @pytest.mark.asyncio
    async def test_get_empty_path(self) -> None:
        tool = MemoryGetTool(_make_provider(MockMemoryManager()))
        call = ToolCall(id="call_1", name="memory_get", arguments={"path": ""})

        result = await tool.execute(call, TEST_CONTEXT)

        assert "error" in result.content
        assert "Path is required" in result.content["error"]

    @pytest.mark.asyncio
    async def test_get_file_not_found(self) -> None:
        manager = MockMemoryManager()
        manager._store.get_chunks_by_location.return_value = []
        tool = MemoryGetTool(_make_provider(manager))
        call = ToolCall(
            id="call_1", name="memory_get", arguments={"path": "nonexistent.md"}
        )

        result = await tool.execute(call, TEST_CONTEXT)

        assert "error" in result.content
        assert "No chunks found" in result.content["error"] or "not found" in result.content["error"].lower()

    @pytest.mark.asyncio
    async def test_get_limits_lines(self) -> None:
        manager = MockMemoryManager()
        manager._store.get_chunks_by_location.return_value = [
            MockChunk(start_line=1, end_line=50, text="chunk one"),
            MockChunk(start_line=51, end_line=100, text="chunk two"),
        ]
        tool = MemoryGetTool(_make_provider(manager))
        call = ToolCall(
            id="call_1",
            name="memory_get",
            arguments={"path": "MEMORY.md", "lines": 500},
        )

        result = await tool.execute(call, TEST_CONTEXT)

        content = result.content
        assert content["to_line"] <= 200 or content["total_chunks"] <= 200
        call_kw = manager._store.get_chunks_by_location.call_args[1]
        assert call_kw["limit"] == 200

    @pytest.mark.asyncio
    async def test_get_nested_path(self) -> None:
        manager = MockMemoryManager()
        manager._store.get_chunks_by_location.return_value = [
            MockChunk(start_line=1, end_line=5, text="Project memory content"),
        ]
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

        assert len(tools) == 3
        names = [t.name for t in tools]
        assert "memory_search" in names
        assert "memory_get" in names
        assert "memory_write" in names

    def test_tools_share_provider(self) -> None:
        provider = _make_provider(MockMemoryManager())
        tools = create_memory_tools(provider)

        search_tool = next(t for t in tools if t.name == "memory_search")
        get_tool = next(t for t in tools if t.name == "memory_get")
        write_tool = next(t for t in tools if t.name == "memory_write")

        assert search_tool._provider is provider
        assert get_tool._provider is provider
        assert write_tool._provider is provider
