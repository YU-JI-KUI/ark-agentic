"""Tests for memory v2 改造: unified rules, prompt rewrites, heading-aware truncation,
conditional memory injection, dream retry counter.
"""

import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ark_agentic.core.memory.rules import HEADING_PRIORITY, MEMORY_FILTER_RULES


# ---------------------------------------------------------------------------
# 改造一: 共享规则常量
# ---------------------------------------------------------------------------


class TestMemoryFilterRules:
    def test_contains_record_section(self) -> None:
        assert "### 记录" in MEMORY_FILTER_RULES

    def test_contains_no_record_section(self) -> None:
        assert "### 不记录" in MEMORY_FILTER_RULES

    def test_contains_positive_negative_examples(self) -> None:
        assert "→ 不记录" in MEMORY_FILTER_RULES
        assert "→ 记录" in MEMORY_FILTER_RULES

    def test_heading_priority_order(self) -> None:
        assert HEADING_PRIORITY == ["身份信息", "回复风格", "业务偏好", "风险偏好"]


class TestRulesReferencedByAllPaths:
    """Verify the shared rules are actually embedded in all three prompts."""

    def test_dream_prompt_contains_filter_rules(self) -> None:
        from ark_agentic.core.memory.dream import _DREAM_PROMPT

        assert "不记录" in _DREAM_PROMPT
        assert "单次操作决策" in _DREAM_PROMPT
        assert "持久偏好" in _DREAM_PROMPT

    def test_flush_prompt_contains_filter_rules(self) -> None:
        from ark_agentic.core.memory.extractor import _FLUSH_PROMPT

        assert "不记录" in _FLUSH_PROMPT
        assert "单次操作决策" in _FLUSH_PROMPT
        assert "持久偏好" in _FLUSH_PROMPT

    def test_memory_write_protocol_contains_filter_rules(self) -> None:
        from ark_agentic.core.prompt.builder import MEMORY_WRITE_PROTOCOL

        assert "不记录" in MEMORY_WRITE_PROTOCOL
        assert "单次操作决策" in MEMORY_WRITE_PROTOCOL
        assert "持久偏好" in MEMORY_WRITE_PROTOCOL


# ---------------------------------------------------------------------------
# 改造二: Dream prompt 不含潜在需求
# ---------------------------------------------------------------------------


class TestDreamPromptRewrite:
    def test_no_latent_needs(self) -> None:
        from ark_agentic.core.memory.dream import _DREAM_PROMPT

        assert "潜在需求" not in _DREAM_PROMPT

    def test_no_step_5_infer(self) -> None:
        from ark_agentic.core.memory.dream import _DREAM_PROMPT

        assert "推断未被明确表达" not in _DREAM_PROMPT

    def test_step3_says_preferences_not_decisions(self) -> None:
        from ark_agentic.core.memory.dream import _DREAM_PROMPT

        assert "保留**所有仍然有效的偏好" in _DREAM_PROMPT
        assert "保留**所有仍然有效的偏好和决策" not in _DREAM_PROMPT

    def test_priority_uses_business_preference(self) -> None:
        from ark_agentic.core.memory.dream import _DREAM_PROMPT

        assert "持久业务偏好" in _DREAM_PROMPT

    def test_runtime_format_works(self) -> None:
        from ark_agentic.core.memory.dream import _DREAM_PROMPT

        result = _DREAM_PROMPT.format(
            current_date="2026-04-15",
            token_count=100,
            memory_content="## 偏好\n简洁",
            session_summaries="user: hi",
        )
        assert "2026-04-15" in result
        assert "{" not in result or '{"distilled"' in result


# ---------------------------------------------------------------------------
# 改造三: Flush prompt 收窄
# ---------------------------------------------------------------------------


class TestFlushPromptTighten:
    def test_no_bare_business_decision(self) -> None:
        from ark_agentic.core.memory.extractor import _FLUSH_PROMPT

        assert "业务决策" not in _FLUSH_PROMPT

    def test_runtime_format_works(self) -> None:
        from ark_agentic.core.memory.extractor import _FLUSH_PROMPT

        result = _FLUSH_PROMPT.format(
            agent_name="Insurance",
            agent_description="保险顾问",
            current_memory="## 偏好\n简洁",
            conversation="user: hi",
        )
        assert "Insurance" in result
        assert "{" not in result or '{"memory"' in result


# ---------------------------------------------------------------------------
# 改造四: Heading-aware truncation
# ---------------------------------------------------------------------------


class TestHeadingAwareTruncation:
    def test_preserves_complete_sections(self) -> None:
        from ark_agentic.core.memory.user_profile import truncate_profile

        content = "## 身份信息\n张三\n\n## 回复风格\n简洁\n\n## 杂项\n" + "长内容 " * 500
        result = truncate_profile(content, max_tokens=50)
        assert "## 身份信息" in result or "张三" in result
        if "杂项" in result:
            assert "长内容" in result

    def test_no_half_sentence(self) -> None:
        from ark_agentic.core.memory.user_profile import (
            parse_heading_sections,
            truncate_profile,
        )

        sections_text = []
        for i in range(10):
            sections_text.append(f"## section{i}\n" + "很长的内容 " * 100)
        content = "\n\n".join(sections_text)
        result = truncate_profile(content, max_tokens=200)
        _, sections = parse_heading_sections(result)
        for _h, body in sections.items():
            assert body.endswith("很长的内容"), f"Section body truncated mid-sentence: {body[-30:]}"

    def test_priority_ordering(self) -> None:
        from ark_agentic.core.memory.user_profile import (
            parse_heading_sections,
            truncate_profile,
        )

        content = (
            "## 风险偏好\n保守型\n\n"
            "## 身份信息\n张三\n\n"
            "## 杂项\n" + "内容 " * 500 + "\n\n"
            "## 回复风格\n简洁"
        )
        result = truncate_profile(content, max_tokens=50)
        _, sections = parse_heading_sections(result)
        assert "身份信息" in sections, "高优先级 heading 被丢弃"

    def test_empty_unchanged(self) -> None:
        from ark_agentic.core.memory.user_profile import truncate_profile

        assert truncate_profile("") == ""

    def test_within_budget_unchanged(self) -> None:
        from ark_agentic.core.memory.user_profile import truncate_profile

        content = "## 身份信息\n张三"
        assert truncate_profile(content, max_tokens=1000) == content


# ---------------------------------------------------------------------------
# 改造五: enable_memory 条件注入
# ---------------------------------------------------------------------------


class TestEnableMemoryGuard:
    def test_memory_section_absent_when_disabled(self) -> None:
        from ark_agentic.core.prompt.builder import SystemPromptBuilder

        prompt = SystemPromptBuilder.quick_build(enable_memory=False)
        assert "<auto_memory_instructions>" not in prompt
        assert "memory_write" not in prompt

    def test_memory_section_present_when_enabled(self) -> None:
        from ark_agentic.core.prompt.builder import SystemPromptBuilder

        prompt = SystemPromptBuilder.quick_build(enable_memory=True)
        assert "<auto_memory_instructions>" in prompt
        assert "memory_write" in prompt

    def test_default_is_disabled(self) -> None:
        from ark_agentic.core.prompt.builder import SystemPromptBuilder

        prompt = SystemPromptBuilder.quick_build()
        assert "<auto_memory_instructions>" not in prompt

    def test_profile_still_injected_without_memory(self) -> None:
        from ark_agentic.core.prompt.builder import SystemPromptBuilder

        prompt = SystemPromptBuilder.quick_build(
            user_profile_content="## 偏好\n简洁",
            enable_memory=False,
        )
        assert "<auto_memory_instructions>" not in prompt
        assert "简洁" in prompt
        assert "<memory_context>" in prompt


# ---------------------------------------------------------------------------
# 改造六: Dream retry counter
# ---------------------------------------------------------------------------


class TestDreamRetryCounter:
    """Retry counter lives on MemoryDreamer; runner has no dream state of its own."""

    def _make_dreamer(self, tmp_path: Path):
        """Build a MemoryDreamer wrapping a failing run() so the retry path runs."""
        from ark_agentic.core.memory.dream import MemoryDreamer
        from ark_agentic.core.memory.manager import build_memory_manager
        from ark_agentic.core.session import SessionManager
        from ark_agentic.core.storage.file.memory import (
            FileMemoryRepository,
        )
        from ark_agentic.core.storage.file.session import (
            FileSessionRepository,
        )

        ws = tmp_path / "ws"
        ws.mkdir(parents=True)
        mm = build_memory_manager(ws)
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()

        dreamer = MemoryDreamer(
            lambda: MagicMock(),
            memory_manager=mm,
            session_manager=SessionManager(
                sessions_dir=sessions_dir,
                repository=FileSessionRepository(sessions_dir),
            ),
            memory_repo=FileMemoryRepository(ws),
        )
        # Force run() to fail so we exercise the retry-counter path.
        dreamer.run = AsyncMock(side_effect=RuntimeError("LLM timeout"))
        return dreamer, ws

    @pytest.mark.asyncio
    async def test_first_failure_does_not_advance_timestamp(self, tmp_path: Path) -> None:
        dreamer, ws = self._make_dreamer(tmp_path)
        user_id = "U001"

        await dreamer._run_with_retry_protection(user_id)

        assert dreamer._failures[user_id] == 1
        assert not (ws / user_id / ".last_dream").exists()

    @pytest.mark.asyncio
    async def test_threshold_advances_timestamp(self, tmp_path: Path) -> None:
        dreamer, ws = self._make_dreamer(tmp_path)
        user_id = "U001"
        dreamer._failures[user_id] = 2

        await dreamer._run_with_retry_protection(user_id)

        assert (ws / user_id / ".last_dream").exists()
        assert user_id not in dreamer._failures

    @pytest.mark.asyncio
    async def test_success_clears_counter(self, tmp_path: Path) -> None:
        from ark_agentic.core.memory.dream import DreamResult, MemoryDreamer
        from ark_agentic.core.memory.manager import build_memory_manager
        from ark_agentic.core.session import SessionManager
        from ark_agentic.core.storage.file.memory import (
            FileMemoryRepository,
        )
        from ark_agentic.core.storage.file.session import (
            FileSessionRepository,
        )

        ws = tmp_path / "ws"
        ws.mkdir(parents=True)
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()
        dreamer = MemoryDreamer(
            lambda: MagicMock(),
            memory_manager=build_memory_manager(ws),
            session_manager=SessionManager(
                sessions_dir=sessions_dir,
                repository=FileSessionRepository(sessions_dir),
            ),
            memory_repo=FileMemoryRepository(ws),
        )
        dreamer.run = AsyncMock(
            return_value=DreamResult(distilled="## 偏好\n简洁", changes="ok")
        )
        dreamer._failures["U001"] = 2

        await dreamer._run_with_retry_protection("U001")

        assert "U001" not in dreamer._failures
