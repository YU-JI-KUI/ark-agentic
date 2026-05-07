"""Tests for BaseAgent skill router wiring and _route_skill_phase."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import pytest

from ark_agentic.core.runtime.base_agent import BaseAgent, RunnerConfig
from ark_agentic.core.session import SessionManager
from ark_agentic.core.skills.base import SkillConfig
from ark_agentic.core.skills.loader import SkillLoader
from ark_agentic.core.skills.router import (
    LLMSkillRouter,
    RouteContext,
    RouteDecision,
    SkillRouter,
)
from ark_agentic.core.tools.registry import ToolRegistry
from ark_agentic.core.types import (
    AgentMessage,
    SkillLoadMode,
)


class _MockLLM:
    async def ainvoke(self, messages, **kwargs):
        class _Msg:
            content = '{"skill_id": null, "reason": ""}'
        return _Msg()


def _make_runner(
    tmp_sessions_dir: Path,
    *,
    load_mode: SkillLoadMode,
    skill_router: SkillRouter | None = None,
):
    import contextlib

    @contextlib.contextmanager
    def _ctx():
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = Path(tmpdir) / "test_skill"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text(
                "---\nname: Test\ndescription: A test\n---\n\nbody"
            )
            cfg = SkillConfig(skill_directories=[tmpdir], load_mode=load_mode)
            loader = SkillLoader(cfg)
            loader.load_from_directories()
            session_manager = SessionManager(tmp_sessions_dir, agent_id="test")
            runner = BaseAgent._construct(
                llm=_MockLLM(),
                session_manager=session_manager,
                tool_registry=ToolRegistry(),
                skill_loader=loader,
                config=RunnerConfig(skill_config=cfg, skill_router=skill_router),
            )
            yield runner

    return _ctx()


def test_runner_config_has_skill_router_field() -> None:
    """RunnerConfig accepts a skill_router argument; default is None."""
    cfg = RunnerConfig()
    assert cfg.skill_router is None


def test_runner_stores_none_router_verbatim(tmp_sessions_dir: Path) -> None:
    """Runner is a dumb pass-through: skill_router=None → _skill_router is None.

    Wiring decisions (default selection, mode validation) live in
    build_standard_agent. Direct BaseAgent construction takes the config
    at face value.
    """
    with _make_runner(
        tmp_sessions_dir, load_mode=SkillLoadMode.dynamic, skill_router=None,
    ) as runner:
        assert runner._skill_router is None


def test_runner_stores_injected_router_verbatim(tmp_sessions_dir: Path) -> None:
    """Caller-supplied router instance is preserved verbatim."""
    custom = LLMSkillRouter(
        llm_factory=lambda: _MockLLM(), history_window=2, timeout=1.0,
    )
    with _make_runner(
        tmp_sessions_dir, load_mode=SkillLoadMode.dynamic, skill_router=custom,
    ) as runner:
        assert runner._skill_router is custom


# ============ _route_skill_phase ============

from ark_agentic.core.runtime.callbacks import CallbackContext


class _RecordingRouter:
    """Router that records the ctx it was called with and returns a fixed decision."""
    history_window = 4
    timeout = 5.0

    def __init__(self, decision: RouteDecision) -> None:
        self.decision = decision
        self.last_ctx: RouteContext | None = None
        self.call_count = 0

    async def route(self, ctx: RouteContext) -> RouteDecision:
        self.call_count += 1
        self.last_ctx = ctx
        return self.decision


@pytest.mark.asyncio
async def test_route_skill_phase_writes_active_skill_id(
    tmp_sessions_dir: Path,
) -> None:
    """_route_skill_phase writes RouteDecision.skill_id to session.state."""
    with _make_runner(
        tmp_sessions_dir, load_mode=SkillLoadMode.dynamic,
    ) as runner:
        skill_id_full = next(iter(runner.skill_loader._skills.keys()))
        runner._skill_router = _RecordingRouter(
            RouteDecision(skill_id=skill_id_full, reason="match"),
        )
        session = runner.session_manager.create_session_sync()
        runner.session_manager.add_message_sync(
            session.session_id, AgentMessage.user("hello"),
        )
        cb_ctx = CallbackContext(
            run_id="r1",
            user_input="hello",
            input_context={},
            session=session,
            metadata={},
        )
        await runner._route_skill_phase(session.session_id, cb_ctx)
        assert session.current_active_skill_id == skill_id_full
        # SSOT lives on session.active_skill_ids, NOT in session.state
        assert "_active_skill_id" not in session.state


@pytest.mark.asyncio
async def test_route_skill_phase_skips_when_no_router(
    tmp_sessions_dir: Path,
) -> None:
    """No-op when self._skill_router is None (e.g., full mode)."""
    with _make_runner(tmp_sessions_dir, load_mode=SkillLoadMode.full) as runner:
        session = runner.session_manager.create_session_sync()
        runner.session_manager.add_message_sync(
            session.session_id, AgentMessage.user("hi"),
        )
        cb_ctx = CallbackContext(
            run_id="r1", user_input="hi", input_context={},
            session=session, metadata={},
        )
        await runner._route_skill_phase(session.session_id, cb_ctx)
        assert session.active_skill_ids == []


@pytest.mark.asyncio
async def test_route_skill_phase_does_not_overwrite_when_decision_none(
    tmp_sessions_dir: Path,
) -> None:
    """Decision.skill_id == None → preserve existing active_skill_ids."""
    with _make_runner(
        tmp_sessions_dir, load_mode=SkillLoadMode.dynamic,
    ) as runner:
        runner._skill_router = _RecordingRouter(
            RouteDecision(skill_id=None, reason="chitchat"),
        )
        session = runner.session_manager.create_session_sync()
        session.set_active_skill_ids(["kept_skill"])
        runner.session_manager.add_message_sync(
            session.session_id, AgentMessage.user("hi"),
        )
        cb_ctx = CallbackContext(
            run_id="r1", user_input="hi", input_context={},
            session=session, metadata={},
        )
        await runner._route_skill_phase(session.session_id, cb_ctx)
        assert session.current_active_skill_id == "kept_skill"


@pytest.mark.asyncio
async def test_route_skill_phase_swallows_router_exceptions(
    tmp_sessions_dir: Path,
) -> None:
    """A buggy router that raises must not bubble up."""
    class _BuggyRouter:
        history_window = 4
        timeout = 5.0
        async def route(self, ctx):
            raise ValueError("contract violation")

    with _make_runner(
        tmp_sessions_dir, load_mode=SkillLoadMode.dynamic,
    ) as runner:
        runner._skill_router = _BuggyRouter()
        session = runner.session_manager.create_session_sync()
        runner.session_manager.add_message_sync(
            session.session_id, AgentMessage.user("hi"),
        )
        cb_ctx = CallbackContext(
            run_id="r1", user_input="hi", input_context={},
            session=session, metadata={},
        )
        await runner._route_skill_phase(session.session_id, cb_ctx)
        assert session.active_skill_ids == []


# ============ run() lifecycle integration ============

from typing import AsyncIterator
from langchain_core.messages import AIMessage, AIMessageChunk


class _MockChatModelForRun:
    """LLM mock that returns one assistant message and supports streaming."""
    def __init__(self) -> None:
        self.call_count = 0

    def bind_tools(self, tools, **kwargs):
        return self

    def model_copy(self, update=None):
        return self

    async def ainvoke(self, messages, **kwargs) -> AIMessage:
        self.call_count += 1
        return AIMessage(content="ok done")

    async def astream(self, messages, **kwargs) -> AsyncIterator[AIMessageChunk]:
        self.call_count += 1
        yield AIMessageChunk(content="ok done")


def _make_runner_with_llm_mock(
    tmp_sessions_dir: Path,
    *,
    skill_router: SkillRouter | None = None,
):
    """Like _make_runner but installs a real LLM mock that supports run()."""
    import contextlib

    @contextlib.contextmanager
    def _ctx():
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = Path(tmpdir) / "test_skill"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text(
                "---\nname: Test\ndescription: A test\n---\n\nbody"
            )
            cfg = SkillConfig(skill_directories=[tmpdir], load_mode=SkillLoadMode.dynamic)
            loader = SkillLoader(cfg)
            loader.load_from_directories()
            session_manager = SessionManager(tmp_sessions_dir, agent_id="test")
            runner = BaseAgent._construct(
                llm=_MockChatModelForRun(),  # type: ignore[arg-type]
                session_manager=session_manager,
                tool_registry=ToolRegistry(),
                skill_loader=loader,
                config=RunnerConfig(
                    skill_config=cfg,
                    skill_router=skill_router,
                    auto_compact=False,
                    max_turns=2,
                ),
            )
            yield runner

    return _ctx()


@pytest.mark.asyncio
async def test_run_invokes_route_skill_phase_before_loop(
    tmp_sessions_dir: Path,
) -> None:
    """run() calls _route_skill_phase between _prepare_session and _run_loop."""
    router = _RecordingRouter(RouteDecision(skill_id=None, reason=""))
    with _make_runner_with_llm_mock(
        tmp_sessions_dir, skill_router=router,
    ) as runner:
        session_id = (await runner.session_manager.create_session(user_id="u1")).session_id
        await runner.run(
            session_id=session_id,
            user_input="hello world",
            user_id="u1",
            stream=False,
        )
        assert router.call_count == 1, "Router should be called exactly once per run()"


@pytest.mark.asyncio
async def test_run_ephemeral_does_not_invoke_router(
    tmp_sessions_dir: Path,
) -> None:
    """run_ephemeral skips _route_skill_phase (subtask context is pre-defined)."""
    router = _RecordingRouter(RouteDecision(skill_id=None, reason=""))
    with _make_runner_with_llm_mock(
        tmp_sessions_dir, skill_router=router,
    ) as runner:
        session_id = runner.session_manager.create_session_sync().session_id
        await runner.run_ephemeral(session_id, "ephemeral input")
        assert router.call_count == 0, "Ephemeral runs must skip router"


@pytest.mark.asyncio
async def test_route_skill_phase_passes_history_and_current_to_router(
    tmp_sessions_dir: Path,
) -> None:
    """Router receives correct RouteContext (history slice + current_active)."""
    with _make_runner(
        tmp_sessions_dir, load_mode=SkillLoadMode.dynamic,
    ) as runner:
        router = _RecordingRouter(RouteDecision(skill_id=None, reason=""))
        runner._skill_router = router
        session = runner.session_manager.create_session_sync()
        session.set_active_skill_ids(["previous"])
        runner.session_manager.add_message_sync(
            session.session_id, AgentMessage.user("first"),
        )
        runner.session_manager.add_message_sync(
            session.session_id, AgentMessage.assistant("first reply"),
        )
        runner.session_manager.add_message_sync(
            session.session_id, AgentMessage.user("second"),
        )
        cb_ctx = CallbackContext(
            run_id="r1", user_input="second", input_context={},
            session=session, metadata={},
        )
        await runner._route_skill_phase(session.session_id, cb_ctx)
        assert router.call_count == 1
        assert router.last_ctx is not None
        assert router.last_ctx.user_input == "second"
        assert router.last_ctx.current_active_skill_id == "previous"
        assert len(router.last_ctx.history) >= 1
        assert len(router.last_ctx.candidate_skills) >= 1


# ============ Multi-turn behavior ============


class _ScriptedRouter:
    """Router that returns a queued list of decisions in order."""
    history_window = 6
    timeout = 5.0

    def __init__(self, decisions: list[RouteDecision]) -> None:
        self._decisions = list(decisions)
        self.received_currents: list[str | None] = []

    async def route(self, ctx: RouteContext) -> RouteDecision:
        self.received_currents.append(ctx.current_active_skill_id)
        if not self._decisions:
            return RouteDecision(skill_id=ctx.current_active_skill_id, reason="exhausted")
        return self._decisions.pop(0)


@pytest.mark.asyncio
async def test_followup_keeps_active_skill_sticky(
    tmp_sessions_dir: Path,
) -> None:
    """Turn 1 picks skill A; turn 2 router decides to keep A → state remains A."""
    with _make_runner_with_llm_mock(tmp_sessions_dir) as runner:
        skill_id = next(iter(runner.skill_loader._skills.keys()))
        runner._skill_router = _ScriptedRouter([
            RouteDecision(skill_id=skill_id, reason="initial"),
            RouteDecision(skill_id=skill_id, reason="followup"),
        ])

        sid = (await runner.session_manager.create_session(user_id="u1")).session_id
        await runner.run(session_id=sid, user_input="帮我看看", user_id="u1", stream=False)
        session = runner.session_manager.get_session_required(sid)
        assert session.current_active_skill_id == skill_id

        await runner.run(session_id=sid, user_input="那再看看", user_id="u1", stream=False)
        session = runner.session_manager.get_session_required(sid)
        assert session.current_active_skill_id == skill_id


@pytest.mark.asyncio
async def test_topic_switch_updates_active_skill(
    tmp_sessions_dir: Path,
) -> None:
    """Turn 2 router selects a different skill → state updated."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Two skills: skill_a, skill_b
        for sid in ("skill_a", "skill_b"):
            d = Path(tmpdir) / sid
            d.mkdir()
            (d / "SKILL.md").write_text(
                f"---\nname: {sid}\ndescription: {sid} desc\n---\n\nbody"
            )
        cfg = SkillConfig(skill_directories=[tmpdir], load_mode=SkillLoadMode.dynamic)
        loader = SkillLoader(cfg)
        loader.load_from_directories()
        ids = list(loader._skills.keys())
        assert len(ids) == 2

        runner = BaseAgent._construct(
            llm=_MockChatModelForRun(),  # type: ignore[arg-type]
            session_manager=SessionManager(tmp_sessions_dir, agent_id="test"),
            tool_registry=ToolRegistry(),
            skill_loader=loader,
            config=RunnerConfig(
                skill_config=cfg,
                auto_compact=False,
                max_turns=2,
            ),
        )
        runner._skill_router = _ScriptedRouter([
            RouteDecision(skill_id=ids[0], reason="topic_a"),
            RouteDecision(skill_id=ids[1], reason="topic_b"),
        ])

        sid = (await runner.session_manager.create_session(user_id="u1")).session_id
        await runner.run(session_id=sid, user_input="A 主题", user_id="u1", stream=False)
        await runner.run(session_id=sid, user_input="切到 B", user_id="u1", stream=False)
        session = runner.session_manager.get_session_required(sid)
        assert session.current_active_skill_id == ids[1]


@pytest.mark.asyncio
async def test_router_sees_model_override_as_current_active(
    tmp_sessions_dir: Path,
) -> None:
    """If a prior turn wrote active_skill_ids (e.g. via read_skill→session_effects),
    router in next turn sees the newest id (active_skill_ids[-1]) as
    current_active_skill_id."""
    with _make_runner_with_llm_mock(tmp_sessions_dir) as runner:
        scripted = _ScriptedRouter([
            RouteDecision(skill_id=None, reason="first"),
            RouteDecision(skill_id=None, reason="second"),
        ])
        runner._skill_router = scripted

        sid = (await runner.session_manager.create_session(user_id="u1")).session_id
        await runner.run(session_id=sid, user_input="t1", user_id="u1", stream=False)
        # Simulate prior-turn activation of a skill on the SSOT
        session = runner.session_manager.get_session_required(sid)
        session.set_active_skill_ids(["model_picked"])
        await runner.run(session_id=sid, user_input="t2", user_id="u1", stream=False)
        # Second router call must have observed model_picked as current (newest-wins)
        assert scripted.received_currents[-1] == "model_picked"
