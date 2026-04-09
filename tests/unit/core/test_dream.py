"""Tests for dream system — periodic memory distillation.

Covers: DreamResult, parse, dream call, optimistic merge apply, gate logic,
session reader, and full run cycle.
"""

import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ark_agentic.core.memory.dream import (
    DreamResult,
    MemoryDreamer,
    format_session_for_dream,
    should_dream,
    touch_last_dream,
)
from ark_agentic.core.memory.user_profile import parse_heading_sections


def _make_llm(response_text: str):
    mock_response = MagicMock()
    mock_response.content = response_text
    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=mock_response)
    return llm


# ---------------------------------------------------------------------------
# DreamResult
# ---------------------------------------------------------------------------


class TestDreamResult:
    def test_empty(self) -> None:
        assert not DreamResult().has_changes

    def test_has_changes(self) -> None:
        assert DreamResult(distilled="## Foo\nbar").has_changes

    def test_whitespace_only(self) -> None:
        assert not DreamResult(distilled="   ").has_changes


# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------


class TestDreamerParse:
    def _parse(self, raw: str) -> DreamResult:
        dreamer = MemoryDreamer(lambda: MagicMock())
        return dreamer._parse_response(raw)

    def test_valid_json(self) -> None:
        result = self._parse('{"distilled": "## A\\nB", "changes": "merged"}')
        assert result.distilled == "## A\nB"
        assert result.changes == "merged"

    def test_empty_json(self) -> None:
        result = self._parse("{}")
        assert not result.has_changes

    def test_no_changes_needed(self) -> None:
        result = self._parse('{"distilled": "", "changes": "无需修改"}')
        assert not result.has_changes

    def test_non_json(self) -> None:
        result = self._parse("I can't parse this")
        assert not result.has_changes

    def test_code_fence(self) -> None:
        raw = '```json\n{"distilled": "## X\\nY", "changes": "ok"}\n```'
        result = self._parse(raw)
        assert result.distilled == "## X\nY"


# ---------------------------------------------------------------------------
# Dream LLM call
# ---------------------------------------------------------------------------


class TestDreamerDream:
    @pytest.mark.asyncio
    async def test_calls_llm_with_sessions(self) -> None:
        llm = _make_llm('{"distilled": "## 偏好\\n简洁", "changes": "merged"}')
        dreamer = MemoryDreamer(lambda: llm)

        result = await dreamer.dream(
            "## 偏好\n简洁\n\n## 偏好\n要简洁",
            session_summaries="user: 我喜欢简洁\nassistant: 好的",
        )

        llm.ainvoke.assert_called_once()
        prompt = llm.ainvoke.call_args[0][0]
        assert "我喜欢简洁" in prompt
        assert "简洁" in result.distilled

    @pytest.mark.asyncio
    async def test_empty_memory_and_sessions(self) -> None:
        dreamer = MemoryDreamer(lambda: MagicMock())
        result = await dreamer.dream("", "")
        assert not result.has_changes

    @pytest.mark.asyncio
    async def test_prompt_includes_date(self) -> None:
        llm = _make_llm('{"distilled": "", "changes": "no changes"}')
        dreamer = MemoryDreamer(lambda: llm)
        await dreamer.dream("## X\nY")
        prompt = llm.ainvoke.call_args[0][0]
        assert "今天是" in prompt

    @pytest.mark.asyncio
    async def test_prompt_includes_token_count(self) -> None:
        llm = _make_llm('{"distilled": "", "changes": "no changes"}')
        dreamer = MemoryDreamer(lambda: llm)
        await dreamer.dream("## X\nY" * 100)
        prompt = llm.ainvoke.call_args[0][0]
        assert "tokens" in prompt


# ---------------------------------------------------------------------------
# Optimistic merge apply
# ---------------------------------------------------------------------------


class TestDreamerApply:
    @pytest.mark.asyncio
    async def test_writes_distilled_with_preamble(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            mem = Path(tmpdir) / "MEMORY.md"
            original = "# Agent Memory\n\n## 旧\n旧内容\n"
            mem.write_text(original, encoding="utf-8")

            dreamer = MemoryDreamer(lambda: MagicMock())
            result = DreamResult(distilled="## 新\n新内容", changes="replaced")
            await dreamer.apply(mem, result, original_snapshot=original)

            content = mem.read_text(encoding="utf-8")
            preamble, sections = parse_heading_sections(content)
            assert preamble == "# Agent Memory"
            assert "新内容" in sections["新"]

    @pytest.mark.asyncio
    async def test_backup_created(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            mem = Path(tmpdir) / "MEMORY.md"
            original = "## 原始\n内容\n"
            mem.write_text(original, encoding="utf-8")

            dreamer = MemoryDreamer(lambda: MagicMock())
            result = DreamResult(distilled="## 新\n新内容", changes="replaced")
            await dreamer.apply(mem, result, original_snapshot=original)

            bak = mem.with_suffix(".md.bak")
            assert bak.exists()
            assert "原始" in bak.read_text(encoding="utf-8")

    @pytest.mark.asyncio
    async def test_optimistic_merge_preserves_concurrent_write(self) -> None:
        """Headings added by memory_write during dream are preserved."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem = Path(tmpdir) / "MEMORY.md"
            original = "## 偏好\n简洁\n"
            mem.write_text(original, encoding="utf-8")

            # Simulate concurrent write
            mem.write_text(
                "## 偏好\n简洁\n\n## 新偏好\n风险保守\n", encoding="utf-8"
            )

            dreamer = MemoryDreamer(lambda: MagicMock())
            result = DreamResult(distilled="## 偏好\n简洁专业", changes="refined")
            await dreamer.apply(mem, result, original_snapshot=original)

            content = mem.read_text(encoding="utf-8")
            _, sections = parse_heading_sections(content)
            assert "简洁专业" in sections["偏好"]
            assert "风险保守" in sections["新偏好"]

    @pytest.mark.asyncio
    async def test_no_write_when_empty_distilled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            mem = Path(tmpdir) / "MEMORY.md"
            original = "## 原始\n内容\n"
            mem.write_text(original, encoding="utf-8")

            dreamer = MemoryDreamer(lambda: MagicMock())
            result = DreamResult(distilled="", changes="无需修改")
            await dreamer.apply(mem, result, original_snapshot=original)

            assert "原始" in mem.read_text(encoding="utf-8")

    @pytest.mark.asyncio
    async def test_empty_distilled_sections_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            mem = Path(tmpdir) / "MEMORY.md"
            original = "## 原始\n内容\n"
            mem.write_text(original, encoding="utf-8")

            dreamer = MemoryDreamer(lambda: MagicMock())
            result = DreamResult(distilled="no headings here", changes="bad output")
            await dreamer.apply(mem, result, original_snapshot=original)

            assert "原始" in mem.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Session reader
# ---------------------------------------------------------------------------


class TestFormatSessionForDream:
    def test_extracts_user_and_assistant(self) -> None:
        from ark_agentic.core.types import AgentMessage

        messages = [
            AgentMessage.system("system prompt"),
            AgentMessage.user("你好"),
            AgentMessage.assistant("你好！"),
        ]
        text = format_session_for_dream(messages)
        assert "user: 你好" in text
        assert "assistant: 你好！" in text
        assert "system" not in text

    def test_empty_messages(self) -> None:
        assert format_session_for_dream([]) == ""


# ---------------------------------------------------------------------------
# Dream gate
# ---------------------------------------------------------------------------


class TestShouldDream:
    def test_first_use_returns_false_and_creates_file(self) -> None:
        with tempfile.TemporaryDirectory() as ws:
            workspace = Path(ws)
            sessions = workspace / "sessions"
            sessions.mkdir()
            user_dir = workspace / "U001"
            user_dir.mkdir()

            result = should_dream("U001", workspace, sessions)

            assert result is False
            assert (user_dir / ".last_dream").exists()

    def test_too_recent_returns_false(self) -> None:
        with tempfile.TemporaryDirectory() as ws:
            workspace = Path(ws)
            sessions = workspace / "sessions"
            sessions.mkdir()

            touch_last_dream("U001", workspace)

            result = should_dream("U001", workspace, sessions, min_hours=24.0)
            assert result is False

    def test_old_enough_but_not_enough_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as ws:
            workspace = Path(ws)
            sessions = workspace / "sessions"
            sessions.mkdir()

            last_dream = workspace / "U001" / ".last_dream"
            last_dream.parent.mkdir(parents=True)
            last_dream.write_text(str(time.time() - 86400 * 2), encoding="utf-8")

            # SessionStore.load will return empty for non-existent user dir
            result = should_dream("U001", workspace, sessions, min_hours=24.0, min_sessions=3)
            assert result is False


class TestTouchLastDream:
    def test_creates_file(self) -> None:
        with tempfile.TemporaryDirectory() as ws:
            touch_last_dream("U001", Path(ws))
            p = Path(ws) / "U001" / ".last_dream"
            assert p.exists()
            ts = float(p.read_text(encoding="utf-8").strip())
            assert time.time() - ts < 5


# ---------------------------------------------------------------------------
# Full run cycle
# ---------------------------------------------------------------------------


class TestDreamerRun:
    @pytest.mark.asyncio
    async def test_full_cycle(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Path(tmpdir) / "ws"
            user_dir = ws / "U001"
            user_dir.mkdir(parents=True)
            mem = user_dir / "MEMORY.md"
            mem.write_text("## 偏好A\n简洁\n\n## 偏好B\n要简洁\n", encoding="utf-8")

            sessions_dir = Path(tmpdir) / "sessions"
            sessions_dir.mkdir()

            llm = _make_llm('{"distilled": "## 偏好\\n简洁回复", "changes": "merged A+B"}')
            dreamer = MemoryDreamer(lambda: llm)

            with patch(
                "ark_agentic.core.memory.dream.read_recent_sessions",
                return_value="user: 我喜欢简洁回复",
            ):
                result = await dreamer.run(mem, sessions_dir, "U001")

            assert result.has_changes
            content = mem.read_text(encoding="utf-8")
            _, sections = parse_heading_sections(content)
            assert len(sections) == 1
            assert "简洁" in sections["偏好"]

            # Last dream timestamp updated
            assert (user_dir / ".last_dream").exists()

    @pytest.mark.asyncio
    async def test_conservative_no_delete(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Path(tmpdir) / "ws"
            user_dir = ws / "U001"
            user_dir.mkdir(parents=True)
            mem = user_dir / "MEMORY.md"
            original = "## 姓名\n张三\n\n## 偏好\n简洁\n"
            mem.write_text(original, encoding="utf-8")

            sessions_dir = Path(tmpdir) / "sessions"
            sessions_dir.mkdir()

            llm = _make_llm('{"distilled": "", "changes": "无需修改"}')
            dreamer = MemoryDreamer(lambda: llm)

            with patch(
                "ark_agentic.core.memory.dream.read_recent_sessions",
                return_value="",
            ):
                result = await dreamer.run(mem, sessions_dir, "U001")

            assert not result.has_changes
            assert mem.read_text(encoding="utf-8") == original
