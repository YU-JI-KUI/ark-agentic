"""Tests for InsuranceIntakeGuard: temperature=0 + few-shot prompt."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from langchain_core.messages import AIMessage

from ark_agentic.agents.insurance.guard import (
    InsuranceIntakeGuard,
    _ADJUST_PATTERNS,
    _NEGATIVE_AMOUNT_RE,
)
from ark_agentic.core.types import AgentMessage


# ---- Helpers ----


def _make_llm(content: str = '{"accepted":true}') -> MagicMock:
    llm = MagicMock()
    llm.model_copy = MagicMock(return_value=llm)
    llm.ainvoke = AsyncMock(return_value=AIMessage(content=content))
    return llm


# ---- Temperature override ----


class TestTemperatureOverride:
    def test_model_copy_called_with_temperature_zero(self) -> None:
        llm = MagicMock()
        llm.model_copy = MagicMock(return_value=llm)

        InsuranceIntakeGuard(llm)

        llm.model_copy.assert_called_once_with(update={"temperature": 0})

    def test_fallback_to_copy(self) -> None:
        llm = MagicMock(spec=[])
        llm.copy = MagicMock(return_value=llm)

        InsuranceIntakeGuard(llm)

        llm.copy.assert_called_once_with(update={"temperature": 0})

    def test_no_copy_method_uses_original(self) -> None:
        llm = MagicMock(spec=[])

        guard = InsuranceIntakeGuard(llm)

        assert guard._llm is llm


# ---- LLM classification ----


class TestLLMClassification:
    @pytest.mark.asyncio
    async def test_accepted(self) -> None:
        llm = _make_llm('{"accepted":true}')
        guard = InsuranceIntakeGuard(llm)

        result = await guard.check("我要领50000")

        assert result.accepted is True
        llm.ainvoke.assert_called_once()

    @pytest.mark.asyncio
    async def test_rejected(self) -> None:
        llm = _make_llm('{"accepted":false,"message":"非保险业务范围"}')
        guard = InsuranceIntakeGuard(llm)

        result = await guard.check("今天天气怎么样")

        assert result.accepted is False
        assert result.message == "非保险业务范围"

    @pytest.mark.asyncio
    async def test_failure_defaults_to_accepted(self) -> None:
        llm = _make_llm()
        llm.ainvoke = AsyncMock(side_effect=RuntimeError("LLM down"))
        guard = InsuranceIntakeGuard(llm)

        result = await guard.check("你好")

        assert result.accepted is True

    @pytest.mark.asyncio
    async def test_malformed_json_defaults_to_accepted(self) -> None:
        llm = _make_llm("not json at all")
        guard = InsuranceIntakeGuard(llm)

        result = await guard.check("你好")

        assert result.accepted is True


# ---- History window ----


class TestHistoryWindow:
    @pytest.mark.asyncio
    async def test_history_passed_to_llm(self) -> None:
        llm = _make_llm('{"accepted":true}')
        guard = InsuranceIntakeGuard(llm)

        history = [
            AgentMessage.user("帮我做个取款方案"),
            AgentMessage.assistant("好的，正在为您制定方案"),
        ]

        await guard.check("这个保单的详情是什么", history=history)

        call_args = llm.ainvoke.call_args[0][0]
        assert len(call_args) == 4  # system + 2 history + current user

    @pytest.mark.asyncio
    async def test_history_window_limit(self) -> None:
        llm = _make_llm('{"accepted":true}')
        guard = InsuranceIntakeGuard(llm)

        history = [
            AgentMessage.user(f"msg_{i}") for i in range(20)
        ]

        await guard.check("这个保单的详情是什么", history=history)

        call_args = llm.ainvoke.call_args[0][0]
        # system(1) + last 10 from history + current user(1) = 12
        assert len(call_args) == 12

    @pytest.mark.asyncio
    async def test_tool_calling_assistant_messages_filtered(self) -> None:
        """Assistant messages with content=None (tool calls) are filtered out."""
        llm = _make_llm('{"accepted":true}')
        guard = InsuranceIntakeGuard(llm)

        history = [
            AgentMessage.user("帮我做个取款方案"),
            AgentMessage.assistant(content=None, tool_calls=[]),  # tool call turn
            AgentMessage.assistant("已为您生成方案"),
        ]

        await guard.check("这个保单的详情是什么", history=history)

        call_args = llm.ainvoke.call_args[0][0]
        # system(1) + user(1) + assistant with content(1) + current user(1) = 4
        # The assistant with content=None is filtered
        assert len(call_args) == 4

    @pytest.mark.asyncio
    async def test_no_history(self) -> None:
        llm = _make_llm('{"accepted":true}')
        guard = InsuranceIntakeGuard(llm)

        await guard.check("我要领50000", history=None)

        call_args = llm.ainvoke.call_args[0][0]
        assert len(call_args) == 2  # system + current user


# ---- Prompt content ----


class TestPromptContent:
    @pytest.mark.asyncio
    async def test_system_prompt_contains_few_shot(self) -> None:
        llm = _make_llm('{"accepted":true}')
        guard = InsuranceIntakeGuard(llm)

        await guard.check("测试")

        call_args = llm.ainvoke.call_args[0][0]
        system_msg = call_args[0]
        assert "领50000" in system_msg.content
        assert "理赔" in system_msg.content
        assert "保费" in system_msg.content

    @pytest.mark.asyncio
    async def test_system_prompt_scope_narrowed(self) -> None:
        llm = _make_llm('{"accepted":true}')
        guard = InsuranceIntakeGuard(llm)

        await guard.check("测试")

        call_args = llm.ainvoke.call_args[0][0]
        system_msg = call_args[0]
        assert "取款" in system_msg.content
        assert "不受理" in system_msg.content

    @pytest.mark.asyncio
    async def test_system_prompt_no_legacy_memory_section(self) -> None:
        llm = _make_llm('{"accepted":true}')
        guard = InsuranceIntakeGuard(llm)

        await guard.check("测试")

        call_args = llm.ainvoke.call_args[0][0]
        system_msg = call_args[0]
        assert "受理范围" in system_msg.content
        assert "取款" in system_msg.content


# ---- Deterministic pre-check (negative amount + adjust phrases with history) ----


class TestDeterministicPreCheck:
    @pytest.mark.asyncio
    async def test_negative_amount_bypasses_llm(self) -> None:
        llm = _make_llm()
        guard = InsuranceIntakeGuard(llm)

        result = await guard.check("取-10000")

        assert result.accepted is True
        llm.ainvoke.assert_not_called()

    def test_negative_amount_regex(self) -> None:
        assert _NEGATIVE_AMOUNT_RE.search("取-10000") is not None
        assert _NEGATIVE_AMOUNT_RE.search("取  -  5") is not None

    @pytest.mark.asyncio
    async def test_adjust_phrase_with_history_bypasses_llm(self) -> None:
        llm = _make_llm()
        guard = InsuranceIntakeGuard(llm)
        history = [AgentMessage.user("帮我做个取款方案")]

        result = await guard.check("零成本方案", history=history)

        assert result.accepted is True
        llm.ainvoke.assert_not_called()

    @pytest.mark.asyncio
    async def test_plan_reference_at_line_start_with_history(self) -> None:
        llm = _make_llm()
        guard = InsuranceIntakeGuard(llm)
        history = [AgentMessage.user("帮我做个取款方案")]

        result = await guard.check("方案2", history=history)

        assert result.accepted is True
        llm.ainvoke.assert_not_called()

    @pytest.mark.asyncio
    async def test_adjust_phrase_without_history_calls_llm(self) -> None:
        llm = _make_llm('{"accepted":true}')
        guard = InsuranceIntakeGuard(llm)

        await guard.check("零成本方案")

        llm.ainvoke.assert_called_once()

    def test_adjust_patterns_cover_expected(self) -> None:
        assert any(p.search("零成本") for p in _ADJUST_PATTERNS)
        assert any(p.search("方案2") for p in _ADJUST_PATTERNS)
