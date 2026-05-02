"""Tests for SkillRouter Protocol, RouteContext, RouteDecision, and LLMSkillRouter."""

from __future__ import annotations

import pytest

from ark_agentic.core.skills.router import (
    RouteContext,
    RouteDecision,
    SkillRouter,
)
from ark_agentic.core.types import (
    AgentMessage,
    SkillEntry,
    SkillMetadata,
)


def _skill(skill_id: str, description: str = "desc") -> SkillEntry:
    return SkillEntry(
        id=skill_id,
        path="/tmp/" + skill_id,
        content="body",
        metadata=SkillMetadata(name=skill_id, description=description),
    )


def test_route_decision_defaults() -> None:
    """RouteDecision has skill_id required and reason defaults to empty."""
    d = RouteDecision(skill_id="s1")
    assert d.skill_id == "s1"
    assert d.reason == ""


def test_route_decision_none_allowed() -> None:
    """skill_id may be None to indicate no activation."""
    d = RouteDecision(skill_id=None, reason="no_match")
    assert d.skill_id is None
    assert d.reason == "no_match"


def test_route_context_construction() -> None:
    """RouteContext accepts the four expected fields."""
    skills = [_skill("a"), _skill("b")]
    ctx = RouteContext(
        user_input="hi",
        history=[AgentMessage.user("hi")],
        current_active_skill_id=None,
        candidate_skills=skills,
    )
    assert ctx.user_input == "hi"
    assert len(ctx.history) == 1
    assert ctx.current_active_skill_id is None
    assert ctx.candidate_skills == skills


# ============ LLMSkillRouter ============

from typing import Any

from ark_agentic.core.skills.router import LLMSkillRouter
from ark_agentic.core.types import (
    AgentToolResult,
    ToolResultType,
)


class _FakeAIMessage:
    """Minimal stand-in for langchain AIMessage."""
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeChatModel:
    """Minimal LLM stub: ainvoke returns a queued response."""
    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.call_count = 0
        self.last_messages: Any = None

    async def ainvoke(self, messages, **kwargs):
        self.call_count += 1
        self.last_messages = messages
        if not self._responses:
            raise RuntimeError("no more responses queued")
        return _FakeAIMessage(self._responses.pop(0))


@pytest.mark.asyncio
async def test_llm_router_returns_valid_skill_id() -> None:
    """Happy path: LLM returns valid JSON with id in candidates."""
    llm = _FakeChatModel(['{"skill_id": "insurance.withdraw", "reason": "user wants to withdraw"}'])
    router = LLMSkillRouter(llm_factory=lambda: llm, history_window=4, timeout=5.0)
    ctx = RouteContext(
        user_input="我想取 5 万",
        history=[AgentMessage.user("我想取 5 万")],
        current_active_skill_id=None,
        candidate_skills=[
            _skill("insurance.withdraw", "保险取款"),
            _skill("insurance.policy_query", "查询保单"),
        ],
    )
    decision = await router.route(ctx)
    assert decision.skill_id == "insurance.withdraw"
    assert "withdraw" in decision.reason or len(decision.reason) > 0
    assert llm.call_count == 1


@pytest.mark.asyncio
async def test_llm_router_prompt_includes_all_signals() -> None:
    """Prompt must include candidates, history, current_active, and latest input."""
    llm = _FakeChatModel(['{"skill_id": "a", "reason": ""}'])
    router = LLMSkillRouter(llm_factory=lambda: llm, history_window=4, timeout=5.0)
    ctx = RouteContext(
        user_input="continue please",
        history=[
            AgentMessage.user("hello"),
            AgentMessage.assistant("hi back"),
        ],
        current_active_skill_id="a",
        candidate_skills=[_skill("a", "alpha skill"), _skill("b", "beta skill")],
    )
    await router.route(ctx)
    sent = str(llm.last_messages)
    assert "alpha skill" in sent
    assert "beta skill" in sent
    assert "hello" in sent
    assert "hi back" in sent
    assert "continue please" in sent
    assert "a" in sent  # current_active_skill_id


@pytest.mark.asyncio
async def test_llm_router_returns_none_when_llm_says_null() -> None:
    """LLM returns explicit null skill_id (e.g., chitchat)."""
    llm = _FakeChatModel(['{"skill_id": null, "reason": "chitchat"}'])
    router = LLMSkillRouter(llm_factory=lambda: llm, history_window=4, timeout=5.0)
    ctx = RouteContext(
        user_input="你好啊",
        history=[],
        current_active_skill_id=None,
        candidate_skills=[_skill("a")],
    )
    decision = await router.route(ctx)
    assert decision.skill_id is None
    assert decision.reason == "chitchat"


@pytest.mark.asyncio
async def test_llm_router_history_includes_tool_turns() -> None:
    llm = _FakeChatModel(['{"skill_id": "a", "reason": ""}'])
    router = LLMSkillRouter(llm_factory=lambda: llm, history_window=4, timeout=5.0)
    tool_msg = AgentMessage.tool([
        AgentToolResult(
            tool_call_id="tc_1",
            result_type=ToolResultType.JSON,
            content={"policies": ["POL001"]},
            llm_digest="[policy_query] 1 policy returned",
        )
    ])
    ctx = RouteContext(
        user_input="POL001 的保额",
        history=[
            AgentMessage.user("帮我看保单"),
            AgentMessage.assistant("查询中"),
            tool_msg,
        ],
        current_active_skill_id="a",
        candidate_skills=[_skill("a")],
    )
    await router.route(ctx)
    sent = str(llm.last_messages)
    assert "[policy_query] 1 policy returned" in sent


@pytest.mark.asyncio
async def test_llm_router_history_a2ui_error_not_swallowed() -> None:
    llm = _FakeChatModel(['{"skill_id": "a", "reason": ""}'])
    router = LLMSkillRouter(llm_factory=lambda: llm, history_window=4, timeout=5.0)
    tool_msg = AgentMessage.tool([
        AgentToolResult.error_result(
            "tc_a2ui_err", "Template missing: withdraw_summary",
        ),
    ])
    from ark_agentic.core.types import ToolCall
    ctx = RouteContext(
        user_input="再来一次",
        history=[
            AgentMessage.assistant(
                content="",
                tool_calls=[ToolCall(id="tc_a2ui_err", name="render_a2ui", arguments={})],
            ),
            tool_msg,
        ],
        current_active_skill_id="a",
        candidate_skills=[_skill("a")],
    )
    await router.route(ctx)
    sent = str(llm.last_messages)
    assert "Template missing: withdraw_summary" in sent
    assert "[已向用户展示卡片" not in sent


# ============ LLMSkillRouter fallback ============

import asyncio


class _SlowChatModel:
    """LLM stub that sleeps longer than router.timeout."""
    async def ainvoke(self, messages, **kwargs):
        await asyncio.sleep(1.0)
        return _FakeAIMessage('{"skill_id": "a", "reason": ""}')


class _RaisingChatModel:
    """LLM stub that raises on call."""
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    async def ainvoke(self, messages, **kwargs):
        raise self._exc


@pytest.mark.asyncio
async def test_llm_router_timeout_preserves_current() -> None:
    """LLM call exceeding timeout returns RouteDecision(current, 'timeout')."""
    llm = _SlowChatModel()
    router = LLMSkillRouter(llm_factory=lambda: llm, history_window=4, timeout=0.05)
    ctx = RouteContext(
        user_input="hi",
        history=[],
        current_active_skill_id="kept_skill",
        candidate_skills=[_skill("kept_skill")],
    )
    decision = await router.route(ctx)
    assert decision.skill_id == "kept_skill"
    assert decision.reason == "timeout"


@pytest.mark.asyncio
async def test_llm_router_timeout_when_no_current_returns_none() -> None:
    """Timeout with no current active returns RouteDecision(None, 'timeout')."""
    llm = _SlowChatModel()
    router = LLMSkillRouter(llm_factory=lambda: llm, history_window=4, timeout=0.05)
    ctx = RouteContext(
        user_input="hi",
        history=[],
        current_active_skill_id=None,
        candidate_skills=[_skill("a")],
    )
    decision = await router.route(ctx)
    assert decision.skill_id is None
    assert decision.reason == "timeout"


@pytest.mark.asyncio
async def test_llm_router_exception_preserves_current() -> None:
    """LLM raising any exception preserves current_active and tags reason."""
    llm = _RaisingChatModel(RuntimeError("boom"))
    router = LLMSkillRouter(llm_factory=lambda: llm, history_window=4, timeout=5.0)
    ctx = RouteContext(
        user_input="hi",
        history=[],
        current_active_skill_id="kept",
        candidate_skills=[_skill("kept")],
    )
    decision = await router.route(ctx)
    assert decision.skill_id == "kept"
    assert decision.reason == "RuntimeError"


@pytest.mark.asyncio
async def test_llm_router_invalid_json_preserves_current() -> None:
    """Non-JSON response → preserve current, reason=parse_error."""
    llm = _FakeChatModel(["this is not json at all"])
    router = LLMSkillRouter(llm_factory=lambda: llm, history_window=4, timeout=5.0)
    ctx = RouteContext(
        user_input="hi",
        history=[],
        current_active_skill_id="kept",
        candidate_skills=[_skill("kept")],
    )
    decision = await router.route(ctx)
    assert decision.skill_id == "kept"
    assert decision.reason == "parse_error"


@pytest.mark.asyncio
async def test_llm_router_skill_id_not_in_candidates_returns_none() -> None:
    """Returned id outside candidate set → None decision."""
    llm = _FakeChatModel(['{"skill_id": "ghost.skill", "reason": "wrong"}'])
    router = LLMSkillRouter(llm_factory=lambda: llm, history_window=4, timeout=5.0)
    ctx = RouteContext(
        user_input="hi",
        history=[],
        current_active_skill_id="real",
        candidate_skills=[_skill("real")],
    )
    decision = await router.route(ctx)
    assert decision.skill_id is None
    assert decision.reason == "invalid_id"


@pytest.mark.asyncio
async def test_llm_router_empty_candidates_short_circuits() -> None:
    """Empty candidate list → no LLM call, reason='no_candidates'."""
    llm = _FakeChatModel([])
    router = LLMSkillRouter(llm_factory=lambda: llm, history_window=4, timeout=5.0)
    ctx = RouteContext(
        user_input="hi",
        history=[],
        current_active_skill_id=None,
        candidate_skills=[],
    )
    decision = await router.route(ctx)
    assert decision.skill_id is None
    assert decision.reason == "no_candidates"
    assert llm.call_count == 0


@pytest.mark.asyncio
async def test_llm_router_handles_fenced_json() -> None:
    """LLM occasionally wraps JSON in ```json ...``` fences — parser tolerates."""
    llm = _FakeChatModel(['```json\n{"skill_id": "a", "reason": "ok"}\n```'])
    router = LLMSkillRouter(llm_factory=lambda: llm, history_window=4, timeout=5.0)
    ctx = RouteContext(
        user_input="hi",
        history=[],
        current_active_skill_id=None,
        candidate_skills=[_skill("a")],
    )
    decision = await router.route(ctx)
    assert decision.skill_id == "a"
    assert decision.reason == "ok"
