"""Integration tests: runner writes display-only metadata to user/assistant messages."""

from __future__ import annotations

from pathlib import Path
from typing import Any, AsyncIterator

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk

from ark_agentic.core.callbacks import (
    CallbackContext,
    CallbackResult,
    HookAction,
    RunnerCallbacks,
)
from ark_agentic.core.memory.manager import MemoryManager, build_memory_manager
from ark_agentic.core.runner import AgentRunner, RunnerConfig
from ark_agentic.core.session import SessionManager
from ark_agentic.core.skills.router import RouteDecision
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


class _RecordingRouter:
    history_window = 4
    timeout = 5.0

    def __init__(self, decision: RouteDecision) -> None:
        self.decision = decision

    async def route(self, ctx: Any) -> RouteDecision:
        return self.decision


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
    memory_manager: MemoryManager | None = None,
    skill_router: Any = None,
) -> AgentRunner:
    llm = _StubLLM(responses=[AIMessage(content="ok")])
    return AgentRunner(
        llm=llm,  # type: ignore[arg-type]
        session_manager=SessionManager(tmp_sessions_dir),
        tool_registry=tool_registry or ToolRegistry(),
        memory_manager=memory_manager,
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
async def test_user_message_carries_no_trace_block(tmp_sessions_dir: Path) -> None:
    """Trace correlation is observability cross-cut — not stored on user messages."""
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
    assert asst_msgs[-1].metadata["active_skill_ids"] == ["skill-a"]


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
    assert "active_skill_ids" not in asst_msgs[-1].metadata
    assert "active_skills_at_turn" not in asst_msgs[-1].metadata


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
    assert "noop" in asst_msgs[-1].metadata["tools_mounted"]


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
    assert "tools_mounted" not in asst_msgs[-1].metadata


@pytest.mark.asyncio
async def test_assistant_carries_memory_used_when_present(
    tmp_sessions_dir: Path, tmp_path: Path,
) -> None:
    """Memory line count from MEMORY.md lands on the assistant message."""
    workspace = tmp_path / "memory_workspace"
    mm = build_memory_manager(workspace)
    await mm.write_memory("u1", "## prefs\nlikes coffee\nlikes cats")
    runner = _make_runner(tmp_sessions_dir, memory_manager=mm)
    session = await runner.session_manager.create_session(user_id="u1")
    await runner.run(
        session_id=session.session_id,
        user_input="hi",
        user_id="u1",
        input_context={"user:id": "u1", "meta:chat_request": {"message_id": "m"}},
        stream=False,
    )
    asst_msgs = [m for m in session.messages if m.role.value == "assistant"]
    assert asst_msgs[-1].metadata["memory_used"] > 0
    assert "_memory_lines" not in session.state, (
        "Side-channel state must be popped after read"
    )


@pytest.mark.asyncio
async def test_assistant_carries_memory_used_zero_when_profile_empty(
    tmp_sessions_dir: Path, tmp_path: Path,
) -> None:
    """When memory is configured but profile is empty, assistant records 0 lines."""
    workspace = tmp_path / "memory_workspace"
    mm = build_memory_manager(workspace)
    runner = _make_runner(tmp_sessions_dir, memory_manager=mm)
    session = await runner.session_manager.create_session(user_id="u1")
    await runner.run(
        session_id=session.session_id,
        user_input="hi",
        user_id="u1",
        input_context={"user:id": "u1", "meta:chat_request": {"message_id": "m"}},
        stream=False,
    )
    asst_msgs = [m for m in session.messages if m.role.value == "assistant"]
    assert asst_msgs[-1].metadata["memory_used"] == 0


@pytest.mark.asyncio
async def test_assistant_omits_memory_used_when_no_memory(
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
    assert "memory_used" not in asst_msgs[-1].metadata


@pytest.mark.asyncio
async def test_assistant_carries_router_decision_when_router_fires(
    tmp_sessions_dir: Path, tmp_path: Path,
) -> None:
    """When the skill router runs, its decision lands on the assistant message."""
    import tempfile
    from ark_agentic.core.skills.base import SkillConfig
    from ark_agentic.core.skills.loader import SkillLoader
    from ark_agentic.core.types import SkillLoadMode

    skill_dir = tmp_path / "skill_x"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: SkillX\ndescription: test skill\n---\n\nbody"
    )
    cfg = SkillConfig(
        skill_directories=[str(tmp_path)], load_mode=SkillLoadMode.dynamic,
    )
    loader = SkillLoader(cfg)
    loader.load_from_directories()
    skill_id = next(iter(loader._skills.keys()))

    router = _RecordingRouter(RouteDecision(skill_id=skill_id, reason="match"))
    runner = AgentRunner(
        llm=_StubLLM(responses=[AIMessage(content="ok")]),  # type: ignore[arg-type]
        session_manager=SessionManager(tmp_sessions_dir),
        tool_registry=ToolRegistry(),
        skill_loader=loader,
        config=RunnerConfig(
            max_turns=2,
            auto_compact=False,
            skill_config=cfg,
            skill_router=router,
        ),
    )
    session = await runner.session_manager.create_session(user_id="u1")
    await runner.run(
        session_id=session.session_id,
        user_input="hi",
        user_id="u1",
        input_context={"user:id": "u1", "meta:chat_request": {"message_id": "m"}},
        stream=False,
    )
    asst_msgs = [m for m in session.messages if m.role.value == "assistant"]
    rd = asst_msgs[-1].metadata["router_decision"]
    assert rd["skill_id"] == skill_id
    assert rd["reason"] == "match"


@pytest.mark.asyncio
async def test_assistant_omits_router_decision_when_router_absent(
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
    assert "router_decision" not in asst_msgs[-1].metadata
