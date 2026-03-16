"""Tests for MemoryExtractor — async memory extraction from conversations."""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from ark_agentic.core.memory.extractor import ExtractedMemory, MemoryExtractor
from ark_agentic.core.memory.user_profile import read_frontmatter, write_frontmatter


class TestExtractedMemory:
    def test_has_content_empty(self) -> None:
        assert not ExtractedMemory().has_content

    def test_has_content_with_profile(self) -> None:
        assert ExtractedMemory(profile={"偏好": {"语言": "中文"}}).has_content

    def test_has_content_with_agent_memory(self) -> None:
        assert ExtractedMemory(agent_memory="some note").has_content


def _make_llm(response_text: str):
    """Create a mock LLM that returns the given text."""
    mock_response = MagicMock()
    mock_response.content = response_text
    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=mock_response)
    return llm


class TestMemoryExtractorParse:
    """Test _parse_response directly."""

    def _parse(self, raw: str) -> ExtractedMemory:
        extractor = MemoryExtractor(lambda: MagicMock())
        return extractor._parse_response(raw)

    def test_empty_input(self) -> None:
        result = self._parse("")
        assert not result.has_content

    def test_empty_json(self) -> None:
        result = self._parse("{}")
        assert not result.has_content

    def test_profile_only(self) -> None:
        result = self._parse('{"profile": {"偏好": {"语言": "中文"}}, "agent_memory": ""}')
        assert result.profile == {"偏好": {"语言": "中文"}}
        assert result.agent_memory == ""

    def test_agent_memory_only(self) -> None:
        result = self._parse('{"profile": {}, "agent_memory": "用户只看第一个保单"}')
        assert result.profile == {}
        assert result.agent_memory == "用户只看第一个保单"

    def test_both(self) -> None:
        result = self._parse(
            '{"profile": {"基本信息": {"姓名": "张三"}}, "agent_memory": "偏好简洁回复"}'
        )
        assert result.profile == {"基本信息": {"姓名": "张三"}}
        assert result.agent_memory == "偏好简洁回复"

    def test_markdown_code_fence(self) -> None:
        raw = '```json\n{"profile": {"偏好": {"x": "y"}}, "agent_memory": ""}\n```'
        result = self._parse(raw)
        assert result.profile == {"偏好": {"x": "y"}}

    def test_non_json_returns_empty(self) -> None:
        result = self._parse("I don't have anything to extract.")
        assert not result.has_content

    def test_malformed_profile_entries_skipped(self) -> None:
        result = self._parse('{"profile": {"偏好": "not a dict"}, "agent_memory": "ok"}')
        assert result.profile == {}
        assert result.agent_memory == "ok"


class TestMemoryExtractorExtract:
    @pytest.mark.asyncio
    async def test_extract_calls_llm(self) -> None:
        llm = _make_llm('{"profile": {"偏好": {"语言": "中文"}}, "agent_memory": ""}')
        extractor = MemoryExtractor(lambda: llm)

        result = await extractor.extract(
            user_message="我喜欢中文回复",
            assistant_response="好的，我会用中文回复您。",
            current_profile={},
            agent_name="保险助手",
            agent_description="提供保险咨询服务",
        )

        llm.ainvoke.assert_called_once()
        assert result.profile == {"偏好": {"语言": "中文"}}


class TestMemoryExtractorSave:
    @pytest.mark.asyncio
    async def test_save_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            profile_path = Path(tmpdir) / "MEMORY.md"
            agent_path = Path(tmpdir) / "agent" / "MEMORY.md"
            write_frontmatter(profile_path, {"基本信息": {}})

            extractor = MemoryExtractor(lambda: MagicMock())
            result = ExtractedMemory(
                profile={"基本信息": {"姓名": "张三"}, "偏好": {"语言": "中文"}},
                agent_memory="",
            )
            await extractor.save(result, profile_path, agent_path)

            data = read_frontmatter(profile_path)
            assert data["基本信息"]["姓名"] == "张三"
            assert data["偏好"]["语言"] == "中文"
            assert not agent_path.exists()

    @pytest.mark.asyncio
    async def test_save_agent_memory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            profile_path = Path(tmpdir) / "profile" / "MEMORY.md"
            agent_path = Path(tmpdir) / "agent" / "MEMORY.md"

            extractor = MemoryExtractor(lambda: MagicMock())
            result = ExtractedMemory(agent_memory="用户只看第一个保单")
            await extractor.save(result, profile_path, agent_path)

            assert agent_path.exists()
            content = agent_path.read_text(encoding="utf-8")
            assert "用户只看第一个保单" in content

    @pytest.mark.asyncio
    async def test_save_both(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            profile_path = Path(tmpdir) / "MEMORY.md"
            agent_path = Path(tmpdir) / "agent" / "MEMORY.md"
            write_frontmatter(profile_path, {})

            extractor = MemoryExtractor(lambda: MagicMock())
            result = ExtractedMemory(
                profile={"偏好": {"语言": "中文"}},
                agent_memory="保单偏好: 只看第一个",
            )
            await extractor.save(result, profile_path, agent_path)

            assert read_frontmatter(profile_path)["偏好"]["语言"] == "中文"
            assert "保单偏好" in agent_path.read_text(encoding="utf-8")

    @pytest.mark.asyncio
    async def test_save_merges_existing_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            profile_path = Path(tmpdir) / "MEMORY.md"
            agent_path = Path(tmpdir) / "agent" / "MEMORY.md"
            write_frontmatter(profile_path, {"基本信息": {"姓名": "李四"}})

            extractor = MemoryExtractor(lambda: MagicMock())
            result = ExtractedMemory(profile={"基本信息": {"时区": "UTC+8"}})
            await extractor.save(result, profile_path, agent_path)

            data = read_frontmatter(profile_path)
            assert data["基本信息"]["姓名"] == "李四"
            assert data["基本信息"]["时区"] == "UTC+8"
