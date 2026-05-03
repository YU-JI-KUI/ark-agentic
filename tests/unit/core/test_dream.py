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
from ark_agentic.core.memory.manager import MemoryManager
from ark_agentic.core.memory.user_profile import parse_heading_sections
from ark_agentic.core.storage.repository.file.agent_state import FileAgentStateRepository
from ark_agentic.core.storage.repository.file.memory import FileMemoryRepository
from ark_agentic.core.storage.repository.file.session import FileSessionRepository


def _make_manager(workspace: Path) -> MemoryManager:
    """Build a real MemoryManager backed by FileMemoryRepository for tests."""
    return MemoryManager(repository=FileMemoryRepository(workspace_dir=workspace))


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
            mgr = _make_manager(Path(tmpdir))
            original = "# Agent Memory\n\n## 旧\n旧内容\n"
            await mgr.overwrite("U001", original)

            dreamer = MemoryDreamer(lambda: MagicMock())
            result = DreamResult(distilled="## 新\n新内容", changes="replaced")
            await dreamer.apply(mgr, "U001", result, original_snapshot=original)

            content = await mgr.read_memory("U001")
            preamble, sections = parse_heading_sections(content)
            assert preamble == "# Agent Memory"
            assert "新内容" in sections["新"]

    @pytest.mark.asyncio
    async def test_optimistic_merge_preserves_concurrent_write(self) -> None:
        """Headings added by memory_write during dream are preserved."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = _make_manager(Path(tmpdir))
            original = "## 偏好\n简洁\n"
            await mgr.overwrite("U001", original)

            # Simulate concurrent write that adds a new heading after the dream snapshot
            await mgr.overwrite(
                "U001", "## 偏好\n简洁\n\n## 新偏好\n风险保守\n"
            )

            dreamer = MemoryDreamer(lambda: MagicMock())
            result = DreamResult(distilled="## 偏好\n简洁专业", changes="refined")
            await dreamer.apply(mgr, "U001", result, original_snapshot=original)

            content = await mgr.read_memory("U001")
            _, sections = parse_heading_sections(content)
            assert "简洁专业" in sections["偏好"]
            assert "风险保守" in sections["新偏好"]

    @pytest.mark.asyncio
    async def test_no_write_when_empty_distilled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = _make_manager(Path(tmpdir))
            original = "## 原始\n内容\n"
            await mgr.overwrite("U001", original)

            dreamer = MemoryDreamer(lambda: MagicMock())
            result = DreamResult(distilled="", changes="无需修改")
            await dreamer.apply(mgr, "U001", result, original_snapshot=original)

            assert "原始" in await mgr.read_memory("U001")

    @pytest.mark.asyncio
    async def test_empty_distilled_sections_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = _make_manager(Path(tmpdir))
            original = "## 原始\n内容\n"
            await mgr.overwrite("U001", original)

            dreamer = MemoryDreamer(lambda: MagicMock())
            result = DreamResult(distilled="no headings here", changes="bad output")
            await dreamer.apply(mgr, "U001", result, original_snapshot=original)

            assert "原始" in await mgr.read_memory("U001")


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
    async def test_first_use_returns_false_and_creates_marker(self) -> None:
        with tempfile.TemporaryDirectory() as ws:
            workspace = Path(ws)
            sessions = workspace / "sessions"
            sessions.mkdir()
            state_repo = FileAgentStateRepository(workspace)
            session_repo = FileSessionRepository(sessions)

            result = await should_dream(state_repo, session_repo, "U001")

            assert result is False
            assert await state_repo.get("U001", "last_dream") is not None

    async def test_too_recent_returns_false(self) -> None:
        with tempfile.TemporaryDirectory() as ws:
            workspace = Path(ws)
            sessions = workspace / "sessions"
            sessions.mkdir()
            state_repo = FileAgentStateRepository(workspace)
            session_repo = FileSessionRepository(sessions)

            await touch_last_dream(state_repo, "U001")

            result = await should_dream(
                state_repo, session_repo, "U001", min_hours=24.0,
            )
            assert result is False

    async def test_old_enough_triggers_even_without_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as ws:
            workspace = Path(ws)
            sessions = workspace / "sessions"
            sessions.mkdir()
            state_repo = FileAgentStateRepository(workspace)
            session_repo = FileSessionRepository(sessions)
            await state_repo.set(
                "U001", "last_dream", str(time.time() - 86400 * 2),
            )

            result = await should_dream(
                state_repo, session_repo, "U001",
                min_hours=24.0, min_sessions=3,
            )
            assert result is True

    async def test_recent_but_enough_sessions_triggers(self) -> None:
        with tempfile.TemporaryDirectory() as ws:
            workspace = Path(ws)
            sessions = workspace / "sessions"
            sessions.mkdir()
            state_repo = FileAgentStateRepository(workspace)
            session_repo = FileSessionRepository(sessions)

            last_ts = time.time() - 3600  # 1h ago
            await state_repo.set("U001", "last_dream", str(last_ts))

            # Seed three real sessions whose updated_at lies after last_ts.
            for i in range(3):
                await session_repo.create(
                    f"s{i}", "U001", model="m", provider="p", state={},
                )
                from ark_agentic.core.persistence import SessionStoreEntry
                await session_repo.update_meta(
                    f"s{i}", "U001",
                    SessionStoreEntry(
                        session_id=f"s{i}",
                        updated_at=int((last_ts + 60 + i) * 1000),
                        model="m", provider="p",
                    ),
                )

            result = await should_dream(
                state_repo, session_repo, "U001",
                min_hours=24.0, min_sessions=3,
            )
            assert result is True

    async def test_both_unsatisfied_returns_false(self) -> None:
        with tempfile.TemporaryDirectory() as ws:
            workspace = Path(ws)
            sessions = workspace / "sessions"
            sessions.mkdir()
            state_repo = FileAgentStateRepository(workspace)
            session_repo = FileSessionRepository(sessions)

            last_ts = time.time() - 3600  # 1h ago
            await state_repo.set("U001", "last_dream", str(last_ts))

            result = await should_dream(
                state_repo, session_repo, "U001",
                min_hours=24.0, min_sessions=3,
            )
            assert result is False


class TestTouchLastDream:
    async def test_creates_marker(self) -> None:
        with tempfile.TemporaryDirectory() as ws:
            state_repo = FileAgentStateRepository(Path(ws))

            await touch_last_dream(state_repo, "U001")

            raw = await state_repo.get("U001", "last_dream")
            assert raw is not None
            ts = float(raw.strip())
            assert time.time() - ts < 5


# ---------------------------------------------------------------------------
# Full run cycle
# ---------------------------------------------------------------------------


class TestDreamerRun:
    @pytest.mark.asyncio
    async def test_full_cycle(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Path(tmpdir) / "ws"
            ws.mkdir(parents=True)
            mgr = _make_manager(ws)
            await mgr.overwrite(
                "U001", "## 偏好A\n简洁\n\n## 偏好B\n要简洁\n"
            )

            sessions_dir = Path(tmpdir) / "sessions"
            sessions_dir.mkdir()

            llm = _make_llm('{"distilled": "## 偏好\\n简洁回复", "changes": "merged A+B"}')
            state_repo = FileAgentStateRepository(ws)
            session_repo = FileSessionRepository(sessions_dir)
            dreamer = MemoryDreamer(
                lambda: llm,
                memory_manager=mgr,
                session_repo=session_repo,
                state_repo=state_repo,
            )

            with patch(
                "ark_agentic.core.memory.dream.read_recent_sessions",
                new=AsyncMock(return_value="user: 我喜欢简洁回复"),
            ):
                result = await dreamer.run("U001")

            assert result.has_changes
            content = await mgr.read_memory("U001")
            _, sections = parse_heading_sections(content)
            assert len(sections) == 1
            assert "简洁" in sections["偏好"]

            # Last dream marker updated via state_repo
            assert await state_repo.get("U001", "last_dream") is not None

    @pytest.mark.asyncio
    async def test_conservative_no_delete(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Path(tmpdir) / "ws"
            ws.mkdir(parents=True)
            mgr = _make_manager(ws)
            original = "## 姓名\n张三\n\n## 偏好\n简洁\n"
            await mgr.overwrite("U001", original)

            sessions_dir = Path(tmpdir) / "sessions"
            sessions_dir.mkdir()

            llm = _make_llm('{"distilled": "", "changes": "无需修改"}')
            state_repo = FileAgentStateRepository(ws)
            session_repo = FileSessionRepository(sessions_dir)
            dreamer = MemoryDreamer(
                lambda: llm,
                memory_manager=mgr,
                session_repo=session_repo,
                state_repo=state_repo,
            )

            with patch(
                "ark_agentic.core.memory.dream.read_recent_sessions",
                new=AsyncMock(return_value=""),
            ):
                result = await dreamer.run("U001")

            assert not result.has_changes
            assert await mgr.read_memory("U001") == original
