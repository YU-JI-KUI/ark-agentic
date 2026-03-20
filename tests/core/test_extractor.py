"""Tests for MemoryFlusher — pre-compaction memory extraction."""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from ark_agentic.core.memory.extractor import FlushResult, MemoryFlusher, _extract_text_from_content


class TestFlushResult:
    def test_has_content_empty(self) -> None:
        assert not FlushResult().has_content

    def test_has_content_with_profile(self) -> None:
        assert FlushResult(profile="## 姓名\n张三").has_content

    def test_has_content_with_agent_memory(self) -> None:
        assert FlushResult(agent_memory="## 偏好\n简洁").has_content


class TestExtractTextFromContent:
    def test_string_content(self) -> None:
        assert _extract_text_from_content("hello") == "hello"

    def test_list_content(self) -> None:
        content = [{"type": "text", "text": "hello "}, {"type": "text", "text": "world"}]
        assert _extract_text_from_content(content) == "hello  world"

    def test_list_with_non_dict(self) -> None:
        content = ["hello", "world"]
        assert _extract_text_from_content(content) == "hello world"

    def test_none_content(self) -> None:
        assert _extract_text_from_content(None) == ""


def _make_llm(response_text: str):
    mock_response = MagicMock()
    mock_response.content = response_text
    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=mock_response)
    return llm


class TestMemoryFlusherParse:
    def _parse(self, raw: str) -> FlushResult:
        flusher = MemoryFlusher(lambda: MagicMock())
        return flusher._parse_response(raw)

    def test_empty_input(self) -> None:
        result = self._parse("")
        assert not result.has_content

    def test_empty_json(self) -> None:
        result = self._parse("{}")
        assert not result.has_content

    def test_profile_only(self) -> None:
        result = self._parse('{"profile": "## 姓名\\n张三", "agent_memory": ""}')
        assert result.profile == "## 姓名\n张三"
        assert result.agent_memory == ""

    def test_agent_memory_only(self) -> None:
        result = self._parse('{"profile": "", "agent_memory": "## 偏好\\n只看第一个保单"}')
        assert result.profile == ""
        assert result.agent_memory == "## 偏好\n只看第一个保单"

    def test_markdown_code_fence(self) -> None:
        raw = '```json\n{"profile": "## 偏好\\n中文", "agent_memory": ""}\n```'
        result = self._parse(raw)
        assert result.profile == "## 偏好\n中文"

    def test_non_json_returns_empty(self) -> None:
        result = self._parse("I don't have anything to extract.")
        assert not result.has_content


class TestMemoryFlusherFlush:
    @pytest.mark.asyncio
    async def test_flush_calls_llm(self) -> None:
        llm = _make_llm('{"profile": "## 姓名\\n张三", "agent_memory": ""}')
        flusher = MemoryFlusher(lambda: llm)

        result = await flusher.flush(
            conversation_text="user: 我叫张三\nassistant: 好的，张三。",
            current_profile="",
            agent_name="保险助手",
            agent_description="提供保险咨询服务",
        )

        llm.ainvoke.assert_called_once()
        assert "张三" in result.profile


class TestMemoryFlusherSave:
    @pytest.mark.asyncio
    async def test_save_agent_memory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            profile_path = Path(tmpdir) / "profile" / "MEMORY.md"
            agent_path = Path(tmpdir) / "agent" / "MEMORY.md"

            flusher = MemoryFlusher(lambda: MagicMock())
            result = FlushResult(agent_memory="## 偏好\n只看第一个保单")
            await flusher.save(result, profile_path, agent_path)

            assert agent_path.exists()
            content = agent_path.read_text(encoding="utf-8")
            assert "只看第一个保单" in content

    def test_append_agent_memory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            memory_path = Path(tmpdir) / "MEMORY.md"
            memory_path.write_text("## 已有\n旧记忆\n", encoding="utf-8")

            flusher = MemoryFlusher(lambda: MagicMock())
            flusher._append_agent_memory("## 新记忆\n内容", memory_path)

            content = memory_path.read_text(encoding="utf-8")
            assert "旧记忆" in content
            assert "新记忆" in content
