"""Tests for MemoryFlusher — pre-compaction memory extraction."""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from ark_agentic.core.memory.extractor import (
    FlushResult,
    MemoryFlusher,
    _extract_text_from_content,
    parse_llm_json,
)


class TestParseLlmJson:
    def test_valid_json(self) -> None:
        assert parse_llm_json('{"key": "value"}') == {"key": "value"}

    def test_empty_string(self) -> None:
        assert parse_llm_json("") is None

    def test_whitespace_only(self) -> None:
        assert parse_llm_json("   ") is None

    def test_non_json(self) -> None:
        assert parse_llm_json("not json at all") is None

    def test_code_fence_json(self) -> None:
        raw = '```json\n{"memory": "test"}\n```'
        result = parse_llm_json(raw)
        assert result == {"memory": "test"}

    def test_code_fence_without_json_tag(self) -> None:
        raw = '```\n{"memory": "test"}\n```'
        result = parse_llm_json(raw)
        assert result == {"memory": "test"}

    def test_non_dict_json_returns_none(self) -> None:
        assert parse_llm_json("[1, 2, 3]") is None

    def test_empty_dict(self) -> None:
        assert parse_llm_json("{}") == {}

    def test_nested_json(self) -> None:
        raw = '{"distilled": "## 偏好\\n简洁", "changes": "merged"}'
        result = parse_llm_json(raw)
        assert result is not None
        assert result["distilled"] == "## 偏好\n简洁"


class TestFlushResult:
    def test_has_content_empty(self) -> None:
        assert not FlushResult().has_content

    def test_has_content_with_memory(self) -> None:
        assert FlushResult(memory="## 姓名\n张三").has_content

    def test_has_content_whitespace_only(self) -> None:
        assert not FlushResult(memory="   ").has_content


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

    def test_memory_present(self) -> None:
        result = self._parse('{"memory": "## 姓名\\n张三"}')
        assert result.memory == "## 姓名\n张三"

    def test_memory_empty(self) -> None:
        result = self._parse('{"memory": ""}')
        assert result.memory == ""

    def test_markdown_code_fence(self) -> None:
        raw = '```json\n{"memory": "## 偏好\\n中文"}\n```'
        result = self._parse(raw)
        assert result.memory == "## 偏好\n中文"

    def test_non_json_returns_empty(self) -> None:
        result = self._parse("I don't have anything to extract.")
        assert not result.has_content


class TestMemoryFlusherFlush:
    @pytest.mark.asyncio
    async def test_flush_calls_llm(self) -> None:
        llm = _make_llm('{"memory": "## 姓名\\n张三"}')
        flusher = MemoryFlusher(lambda: llm)

        result = await flusher.flush(
            conversation_text="user: 我叫张三\nassistant: 好的，张三。",
            current_memory="",
            agent_name="保险助手",
            agent_description="提供保险咨询服务",
        )

        llm.ainvoke.assert_called_once()
        assert "张三" in result.memory


class TestMemoryFlusherSave:
    @pytest.mark.asyncio
    async def test_save_memory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            memory_path = Path(tmpdir) / "user1" / "MEMORY.md"

            flusher = MemoryFlusher(lambda: MagicMock())
            result = FlushResult(memory="## 偏好\n只看第一个保单")
            await flusher.save(result, memory_path)

            assert memory_path.exists()
            content = memory_path.read_text(encoding="utf-8")
            assert "只看第一个保单" in content

    @pytest.mark.asyncio
    async def test_save_upserts_headings(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            memory_path = Path(tmpdir) / "MEMORY.md"
            memory_path.write_text("## 已有\n旧记忆\n", encoding="utf-8")

            flusher = MemoryFlusher(lambda: MagicMock())
            result = FlushResult(memory="## 新记忆\n内容")
            await flusher.save(result, memory_path)

            content = memory_path.read_text(encoding="utf-8")
            assert "旧记忆" in content
            assert "新记忆" in content
