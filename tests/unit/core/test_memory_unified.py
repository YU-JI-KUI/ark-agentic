"""Regression tests for unified memory model.

Validates the single-store-per-user memory model with PR2.5 abstraction:
- All writes go through MemoryRepository (file backend by default)
- Heading-based upsert semantics
- Preamble preserved
- Flush writes to user's memory store
- System prompt reads via MemoryManager (no direct profile loaders)
"""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from ark_agentic.core.memory.manager import MemoryManager
from ark_agentic.core.memory.user_profile import parse_heading_sections
from ark_agentic.core.memory.extractor import FlushResult, MemoryFlusher
from ark_agentic.core.storage.backends.file.memory import FileMemoryRepository
from ark_agentic.core.tools.memory import MemoryWriteTool, MemoryProvider
from ark_agentic.core.types import ToolCall


def _make_manager(ws: str) -> MemoryManager:
    return MemoryManager(repository=FileMemoryRepository(workspace_dir=ws))


def _provider(mgr: MemoryManager) -> MemoryProvider:
    return lambda uid: mgr


CTX = {"user:id": "U001"}


class TestMemoryManagerMinimal:
    async def test_read_memory_empty(self) -> None:
        with tempfile.TemporaryDirectory() as ws:
            mgr = _make_manager(ws)
            assert await mgr.read_memory("U001") == ""

    async def test_write_and_read(self) -> None:
        with tempfile.TemporaryDirectory() as ws:
            mgr = _make_manager(ws)
            await mgr.write_memory("U001", "## 姓名\n张三")
            content = await mgr.read_memory("U001")
            assert "张三" in content

    async def test_write_returns_empty_no_heading(self) -> None:
        with tempfile.TemporaryDirectory() as ws:
            mgr = _make_manager(ws)
            current, dropped = await mgr.write_memory("U001", "no heading")
            assert current == []
            assert dropped == []


class TestWriteToolUnified:
    async def test_writes_to_user_subdir(self) -> None:
        with tempfile.TemporaryDirectory() as ws:
            mgr = _make_manager(ws)
            tool = MemoryWriteTool(_provider(mgr))
            call = ToolCall(
                id="c1", name="memory_write",
                arguments={"content": "## 偏好\n简洁"},
            )
            result = await tool.execute(call, CTX)
            assert result.content["saved"] is True
            content = await mgr.read_memory("U001")
            assert "简洁" in content


class TestWriteDeduplicatesHeadings:
    async def test_same_heading_twice(self) -> None:
        with tempfile.TemporaryDirectory() as ws:
            mgr = _make_manager(ws)
            tool = MemoryWriteTool(_provider(mgr))

            for content in ["## 渠道偏好\n不要保单贷款", "## 渠道偏好\n排除 policy_loan"]:
                call = ToolCall(id="c1", name="memory_write", arguments={"content": content})
                await tool.execute(call, CTX)

            text = await mgr.read_memory("U001")
            _, sections = parse_heading_sections(text)
            assert len(sections) == 1
            assert "policy_loan" in sections["渠道偏好"]


class TestWritePreservesPreamble:
    async def test_preamble_survives_upsert(self) -> None:
        with tempfile.TemporaryDirectory() as ws:
            mgr = _make_manager(ws)
            # Seed with preamble + heading via overwrite
            await mgr.overwrite("U001", "# Agent Memory\n\n## 姓名\n张三\n")

            tool = MemoryWriteTool(_provider(mgr))
            call = ToolCall(id="c1", name="memory_write", arguments={"content": "## 偏好\n简洁"})
            await tool.execute(call, CTX)

            content = await mgr.read_memory("U001")
            assert "# Agent Memory" in content
            _, sections = parse_heading_sections(content)
            assert sections["姓名"] == "张三"
            assert sections["偏好"] == "简洁"


class TestFlushWritesSinglePath:
    async def test_flush_writes_via_manager(self) -> None:
        with tempfile.TemporaryDirectory() as ws:
            mgr = _make_manager(ws)
            flusher = MemoryFlusher(lambda: MagicMock())
            result = FlushResult(memory="## 新偏好\n详细")
            await flusher.save(result, mgr, "U001")

            content = await mgr.read_memory("U001")
            assert "新偏好" in content

    async def test_flush_callback_uses_manager_api(self) -> None:
        with tempfile.TemporaryDirectory() as ws:
            llm_response = MagicMock()
            llm_response.content = '{"memory": "## 偏好\\n简洁"}'
            llm = MagicMock()
            llm.ainvoke = AsyncMock(return_value=llm_response)

            flusher = MemoryFlusher(lambda: llm)
            prompt_config = MagicMock()
            prompt_config.agent_name = "助手"
            prompt_config.agent_description = "测试"

            mgr = _make_manager(ws)
            callback = flusher.make_pre_compact_callback("U001", prompt_config, mgr)

            msg = MagicMock()
            msg.role.value = "user"
            msg.content = "我喜欢简洁"
            await callback("sess1", [msg])

            content = await mgr.read_memory("U001")
            assert "简洁" in content


class TestSystemPromptReadsWorkspace:
    def test_no_profiles_import(self) -> None:
        from ark_agentic.core.runner import AgentRunner
        import inspect
        source = inspect.getsource(AgentRunner._build_system_prompt)
        assert "load_user_profile" not in source
        assert "get_memory_base_dir" not in source
