"""Integration tests: runner writes display-only fields to user/assistant messages."""

from __future__ import annotations

from pathlib import Path
from typing import Any, AsyncIterator

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk

from ark_agentic.core.runtime.callbacks import (
    CallbackContext,
    CallbackResult,
    HookAction,
    RunnerCallbacks,
)
from ark_agentic.core.runtime.base_agent import BaseAgent, RunnerConfig
from ark_agentic.core.session import SessionManager
from ark_agentic.core.tools.base import AgentTool
from ark_agentic.core.tools.registry import ToolRegistry
from ark_agentic.core.types import AgentToolResult, ToolCall


class _DummyTool(AgentTool):
    name = "noop"
    description = "no-op test tool"
    parameters = []

    async def execute(
        self, tool_call: ToolCall, context: dict[str, Any] | None = None
    ) -> AgentToolResult:
        return AgentToolResult.text_result(tool_call.id, "ok")


class _StubLLM:
    """Mimics the BaseChatModel surface LLMCaller depends on."""

    model = "stub-model"
    temperature = 0.5
    top_p = 0.9

    def __init__(self, responses: list[AIMessage]) -> None:
        self._responses = responses
        self._idx = 0

    def bind_tools(self, tools: list[Any], **kw: Any) -> "_StubLLM":
        return self

    def model_copy(self, update: dict[str, Any] | None = None) -> "_StubLLM":
        return self

    async def ainvoke(self, messages: list[Any], **kw: Any) -> AIMessage:
        if self._idx >= len(self._responses):
            raise RuntimeError("ainvoke called more times than stubbed")
        msg = self._responses[self._idx]
        self._idx += 1
        return msg

    async def astream(
        self, messages: list[Any], **kw: Any
    ) -> AsyncIterator[AIMessageChunk]:
        if False:  # pragma: no cover
            yield AIMessageChunk(content="")


def _make_runner(
    tmp_sessions_dir: Path,
    *,
    callbacks: RunnerCallbacks | None = None,
    tool_registry: ToolRegistry | None = None,
    skill_router: Any = None,
) -> BaseAgent:
    llm = _StubLLM(responses=[AIMessage(content="ok")])
    return BaseAgent._construct(
        llm=llm,  # type: ignore[arg-type]
        session_manager=SessionManager(tmp_sessions_dir, agent_id="test"),
        tool_registry=tool_registry or ToolRegistry(),
        config=RunnerConfig(
            max_turns=2, auto_compact=False, skill_router=skill_router,
        ),
        callbacks=callbacks,
    )


@pytest.mark.asyncio
async def test_user_message_carries_chat_request_normal_path(tmp_sessions_dir: Path) -> None:
    runner = _make_runner(tmp_sessions_dir)
    session = await runner.session_manager.create_session(user_id="u1")
    input_context = {
        "user:id": "u1",
        "meta:chat_request": {"agent_id": "x", "message_id": "m1"},
    }
    await runner.run(
        session_id=session.session_id,
        user_input="hello",
        user_id="u1",
        input_context=input_context,
        stream=False,
    )
    user_msgs = [m for m in session.messages if m.role.value == "user"]
    assert user_msgs
    last = user_msgs[-1]
    assert last.metadata["chat_request"] == {"agent_id": "x", "message_id": "m1"}
    assert "meta:chat_request" not in last.metadata


@pytest.mark.asyncio
async def test_user_message_carries_chat_request_on_abort(tmp_sessions_dir: Path) -> None:
    async def abort_hook(ctx: CallbackContext, **_kw: Any) -> CallbackResult:
        return CallbackResult(action=HookAction.ABORT)

    callbacks = RunnerCallbacks(before_agent=[abort_hook])
    runner = _make_runner(tmp_sessions_dir, callbacks=callbacks)
    session = await runner.session_manager.create_session(user_id="u1")
    input_context = {
        "user:id": "u1",
        "meta:chat_request": {"agent_id": "x", "message_id": "m1"},
    }
    await runner.run(
        session_id=session.session_id,
        user_input="hello",
        user_id="u1",
        input_context=input_context,
        stream=False,
    )
    user_msgs = [m for m in session.messages if m.role.value == "user"]
    assert user_msgs
    assert user_msgs[-1].metadata["chat_request"] == {
        "agent_id": "x", "message_id": "m1",
    }


@pytest.mark.asyncio
async def test_user_message_carries_trace_id_when_span_active(
    tmp_sessions_dir: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: the user message must carry ``trace.trace_id`` so the
    Studio "View in trace" button works on user turns (previously only
    assistant turns had this stamped, leaving the button disabled with
    'No trace_id captured for this message' for users).

    Patches ``current_trace_id_or_none`` rather than installing a real OTel
    TracerProvider — OTel's global provider is a process-wide singleton
    that other test modules contend for, and we only need to verify the
    runner consults the helper and writes its return value through.
    """
    fake_trace_id = "a" * 32
    monkeypatch.setattr(
        "ark_agentic.core.observability.current_trace_id_or_none",
        lambda: fake_trace_id,
    )

    runner = _make_runner(tmp_sessions_dir)
    session = await runner.session_manager.create_session(user_id="u1")
    await runner.run(
        session_id=session.session_id,
        user_input="hello",
        user_id="u1",
        input_context={
            "user:id": "u1",
            "meta:chat_request": {"message_id": "m"},
        },
        stream=False,
    )
    user_msgs = [m for m in session.messages if m.role.value == "user"]
    assert user_msgs[-1].metadata["trace"]["trace_id"] == fake_trace_id

    asst_msgs = [m for m in session.messages if m.role.value == "assistant"]
    assert asst_msgs[-1].metadata["trace"]["trace_id"] == fake_trace_id


@pytest.mark.asyncio
async def test_user_message_omits_trace_block_when_helper_returns_none(
    tmp_sessions_dir: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When no trace span is active (helper returns None) the user message
    must not gain a stale empty trace block — Studio renders the button as
    disabled in that case."""
    monkeypatch.setattr(
        "ark_agentic.core.observability.current_trace_id_or_none",
        lambda: None,
    )

    runner = _make_runner(tmp_sessions_dir)
    session = await runner.session_manager.create_session(user_id="u1")
    await runner.run(
        session_id=session.session_id,
        user_input="hello",
        user_id="u1",
        input_context={"user:id": "u1", "meta:chat_request": {"message_id": "m"}},
        stream=False,
    )
    user_msgs = [m for m in session.messages if m.role.value == "user"]
    assert "trace" not in user_msgs[-1].metadata


@pytest.mark.asyncio
async def test_assistant_message_carries_active_skill_ids(tmp_sessions_dir: Path) -> None:
    runner = _make_runner(tmp_sessions_dir)
    session = await runner.session_manager.create_session(user_id="u1")
    runner.session_manager.set_active_skill_ids(session.session_id, ["skill-a"])
    await runner.run(
        session_id=session.session_id,
        user_input="hi",
        user_id="u1",
        input_context={"user:id": "u1", "meta:chat_request": {"agent_id": "x", "message_id": "m"}},
        stream=False,
    )
    asst_msgs = [m for m in session.messages if m.role.value == "assistant"]
    assert asst_msgs
    assert asst_msgs[-1].turn_context is not None
    assert asst_msgs[-1].turn_context.active_skill_id == "skill-a"


@pytest.mark.asyncio
async def test_assistant_skips_active_skill_ids_when_empty(tmp_sessions_dir: Path) -> None:
    runner = _make_runner(tmp_sessions_dir)
    session = await runner.session_manager.create_session(user_id="u1")
    await runner.run(
        session_id=session.session_id,
        user_input="hi",
        user_id="u1",
        input_context={"user:id": "u1", "meta:chat_request": {"agent_id": "x", "message_id": "m"}},
        stream=False,
    )
    asst_msgs = [m for m in session.messages if m.role.value == "assistant"]
    assert asst_msgs[-1].turn_context is not None
    assert asst_msgs[-1].turn_context.active_skill_id is None


@pytest.mark.asyncio
async def test_assistant_carries_tools_mounted(tmp_sessions_dir: Path) -> None:
    """Tools exposed to the LLM this turn land on the assistant message."""
    registry = ToolRegistry()
    registry.register(_DummyTool())
    runner = _make_runner(tmp_sessions_dir, tool_registry=registry)
    session = await runner.session_manager.create_session(user_id="u1")
    await runner.run(
        session_id=session.session_id,
        user_input="hi",
        user_id="u1",
        input_context={"user:id": "u1", "meta:chat_request": {"message_id": "m"}},
        stream=False,
    )
    asst_msgs = [m for m in session.messages if m.role.value == "assistant"]
    assert asst_msgs[-1].turn_context is not None
    assert "noop" in asst_msgs[-1].turn_context.tools_mounted


@pytest.mark.asyncio
async def test_assistant_omits_tools_mounted_when_no_tools(
    tmp_sessions_dir: Path,
) -> None:
    runner = _make_runner(tmp_sessions_dir)
    session = await runner.session_manager.create_session(user_id="u1")
    await runner.run(
        session_id=session.session_id,
        user_input="hi",
        user_id="u1",
        input_context={"user:id": "u1", "meta:chat_request": {"message_id": "m"}},
        stream=False,
    )
    asst_msgs = [m for m in session.messages if m.role.value == "assistant"]
    assert asst_msgs[-1].turn_context is not None
    assert asst_msgs[-1].turn_context.tools_mounted == []


# memory_used and router_decision were removed entirely. The router outcome
# is reflected in session.active_skill_ids (SSOT) and captured in
# turn_context.active_skill_id; no per-message stash is needed.
