"""Tests for memory_write tool (upsert + empty=delete semantics)."""

import tempfile
from pathlib import Path

import pytest

from ark_agentic.core.memory.manager import MemoryManager, build_memory_manager
from ark_agentic.core.tools.memory import (
    MemoryWriteTool,
    create_memory_tools,
    MemoryProvider,
)
from ark_agentic.core.types import ToolCall


def _make_manager(workspace_dir: str) -> MemoryManager:
    return build_memory_manager(workspace_dir)


def _provider(mgr: MemoryManager) -> MemoryProvider:
    return lambda uid: mgr


CTX = {"user:id": "test_user"}


class TestMemoryWriteTool:
    def test_tool_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as ws:
            tool = MemoryWriteTool(_provider(_make_manager(ws)))
            assert tool.name == "memory_write"
            assert len(tool.parameters) == 1

    def test_description_mentions_upsert(self) -> None:
        with tempfile.TemporaryDirectory() as ws:
            tool = MemoryWriteTool(_provider(_make_manager(ws)))
            assert "增量" in tool.description

    @pytest.mark.asyncio
    async def test_write_returns_current_headings(self) -> None:
        with tempfile.TemporaryDirectory() as ws:
            tool = MemoryWriteTool(_provider(_make_manager(ws)))
            call = ToolCall(
                id="c1", name="memory_write",
                arguments={"content": "## 风险偏好\n保守型\n\n## 回复风格\n简洁"},
            )
            result = await tool.execute(call, CTX)
            assert result.content["saved"] is True
            assert "风险偏好" in result.content["current_headings"]
            assert "回复风格" in result.content["current_headings"]

            mem = Path(ws) / "test_user" / "MEMORY.md"
            assert mem.exists()
            assert "保守型" in mem.read_text(encoding="utf-8")

    @pytest.mark.asyncio
    async def test_write_empty_content(self) -> None:
        with tempfile.TemporaryDirectory() as ws:
            tool = MemoryWriteTool(_provider(_make_manager(ws)))
            call = ToolCall(id="c1", name="memory_write", arguments={"content": ""})
            result = await tool.execute(call, CTX)
            assert result.content["saved"] is False

    @pytest.mark.asyncio
    async def test_write_no_heading_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as ws:
            tool = MemoryWriteTool(_provider(_make_manager(ws)))
            call = ToolCall(
                id="c1", name="memory_write",
                arguments={"content": "plain text no heading"},
            )
            result = await tool.execute(call, CTX)
            assert result.content["saved"] is False
            assert "heading" in result.content["error"].lower()

    @pytest.mark.asyncio
    async def test_write_missing_user_id(self) -> None:
        with tempfile.TemporaryDirectory() as ws:
            tool = MemoryWriteTool(_provider(_make_manager(ws)))
            call = ToolCall(id="c1", name="memory_write", arguments={"content": "## X\nY"})
            result = await tool.execute(call, {})
            assert result.content["saved"] is False
            assert "user:id" in result.content["error"]

    @pytest.mark.asyncio
    async def test_upsert_preserves_other_headings(self) -> None:
        """Upsert: writing new headings does NOT remove existing ones."""
        with tempfile.TemporaryDirectory() as ws:
            tool = MemoryWriteTool(_provider(_make_manager(ws)))

            call1 = ToolCall(
                id="c1", name="memory_write",
                arguments={"content": "## A\nval_a\n\n## B\nval_b"},
            )
            r1 = await tool.execute(call1, CTX)
            assert set(r1.content["current_headings"]) == {"A", "B"}

            call2 = ToolCall(
                id="c2", name="memory_write",
                arguments={"content": "## A\nval_a_updated\n\n## C\nval_c"},
            )
            r2 = await tool.execute(call2, CTX)
            assert set(r2.content["current_headings"]) == {"A", "B", "C"}
            assert "dropped_headings" not in r2.content

            mem = Path(ws) / "test_user" / "MEMORY.md"
            text = mem.read_text(encoding="utf-8")
            assert "val_a_updated" in text
            assert "val_b" in text
            assert "val_c" in text

    @pytest.mark.asyncio
    async def test_empty_body_deletes_heading(self) -> None:
        """Writing a heading with empty body deletes it."""
        with tempfile.TemporaryDirectory() as ws:
            tool = MemoryWriteTool(_provider(_make_manager(ws)))

            call1 = ToolCall(
                id="c1", name="memory_write",
                arguments={"content": "## 贷款偏好\n不显示退保方案\n\n## 回复风格\n简洁"},
            )
            await tool.execute(call1, CTX)

            call2 = ToolCall(
                id="c2", name="memory_write",
                arguments={"content": "## 贷款偏好\n\n## 取款偏好\n不显示贷款方案"},
            )
            r2 = await tool.execute(call2, CTX)
            assert "取款偏好" in r2.content["current_headings"]
            assert "回复风格" in r2.content["current_headings"]
            assert "贷款偏好" not in r2.content["current_headings"]
            assert r2.content["dropped_headings"] == ["贷款偏好"]

            mem = Path(ws) / "test_user" / "MEMORY.md"
            text = mem.read_text(encoding="utf-8")
            assert "贷款偏好" not in text
            assert "取款偏好" in text
            assert "回复风格" in text

    @pytest.mark.asyncio
    async def test_upsert_does_not_lose_unrelated_headings(self) -> None:
        """Core safety: adding one heading never loses another."""
        with tempfile.TemporaryDirectory() as ws:
            mgr = _make_manager(ws)
            mem = Path(ws) / "test_user" / "MEMORY.md"
            mem.parent.mkdir(parents=True)
            mem.write_text("## 身份信息\n张经理\n\n## 回复风格\n简洁\n", encoding="utf-8")

            tool = MemoryWriteTool(_provider(mgr))
            call = ToolCall(
                id="c1", name="memory_write",
                arguments={"content": "## 业务偏好\n不显示贷款方案"},
            )
            r = await tool.execute(call, CTX)
            assert set(r.content["current_headings"]) == {"身份信息", "回复风格", "业务偏好"}
            assert "dropped_headings" not in r.content

            text = mem.read_text(encoding="utf-8")
            assert "张经理" in text
            assert "简洁" in text
            assert "不显示贷款方案" in text


class TestCreateMemoryTools:
    def test_only_write_tool(self) -> None:
        with tempfile.TemporaryDirectory() as ws:
            tools = create_memory_tools(_provider(_make_manager(ws)))
            assert len(tools) == 1
            assert tools[0].name == "memory_write"
