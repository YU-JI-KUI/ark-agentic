"""Unit tests for runner refactor: _dispatch_event, _run_hooks event routing, _LoopState."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from ark_agentic.core.runtime.callbacks import (
    CallbackContext,
    CallbackEvent,
    CallbackResult,
    RunnerCallbacks,
)
from ark_agentic.core.runtime.runner import AgentRunner, RunnerConfig, RunResult, _LoopState
from ark_agentic.core.skills.base import SkillConfig
from ark_agentic.core.types import AgentMessage, SessionEntry, SkillLoadMode, ToolCall


class TestDispatchEvent:
    """AgentRunner._dispatch_event routes CallbackEvent to AgentEventHandler methods."""

    def test_step_routes_to_on_step_with_text(self) -> None:
        handler = MagicMock()
        AgentRunner._dispatch_event(
            handler, CallbackEvent(type="step", data={"text": "doing work"}),
        )
        handler.on_step.assert_called_once_with("doing work")
        handler.on_ui_component.assert_not_called()
        handler.on_custom_event.assert_not_called()

    def test_step_empty_string_when_text_missing(self) -> None:
        handler = MagicMock()
        AgentRunner._dispatch_event(handler, CallbackEvent(type="step", data={}))
        handler.on_step.assert_called_once_with("")

    def test_ui_component_routes_to_on_ui_component(self) -> None:
        handler = MagicMock()
        payload = {"source_type": "x", "query_msg": "y"}
        AgentRunner._dispatch_event(
            handler, CallbackEvent(type="ui_component", data=payload),
        )
        handler.on_ui_component.assert_called_once_with(payload)
        handler.on_step.assert_not_called()

    def test_other_types_route_to_on_custom_event(self) -> None:
        handler = MagicMock()
        AgentRunner._dispatch_event(
            handler, CallbackEvent(type="intake_rejected", data={"relevant": 0}),
        )
        handler.on_custom_event.assert_called_once_with("intake_rejected", {"relevant": 0})
        handler.on_step.assert_not_called()
        handler.on_ui_component.assert_not_called()


class TestRunHooksEventDispatch:
    """_run_hooks uses _dispatch_event (integration with mock handler)."""

    @pytest.fixture
    def minimal_runner(self) -> AgentRunner:
        config = RunnerConfig(
            skill_config=SkillConfig(load_mode=SkillLoadMode.full),
        )
        runner = AgentRunner(
            llm=Mock(),
            session_manager=Mock(),
            tool_registry=Mock(),
            config=config,
        )
        runner._run_loop = AsyncMock(
            return_value=RunResult(response=AgentMessage.assistant("mock")),
        )  # type: ignore
        runner.session_manager.get_session_required = Mock(
            side_effect=lambda sid: SessionEntry(session_id=sid, user_id="u"),
        )
        runner.session_manager.add_message_sync = Mock()
        runner.session_manager.auto_compact_if_needed = AsyncMock()
        runner.session_manager.sync_pending_messages = AsyncMock()
        runner.session_manager.sync_session_state = AsyncMock()
        runner._memory_manager = None
        return runner

    @pytest.mark.asyncio
    async def test_hook_event_dispatched_to_custom(self, minimal_runner: AgentRunner) -> None:
        handler = MagicMock()

        async def hook(ctx: CallbackContext, **kwargs: object) -> CallbackResult:
            return CallbackResult(
                event=CallbackEvent(type="start_flow", data={"source_type": "bonus"}),
            )

        minimal_runner._callbacks = RunnerCallbacks(before_agent=[hook])
        cb_ctx = CallbackContext(
            run_id="r1",
            user_input="ok",
            input_context={},
            session=SessionEntry(session_id="s1", user_id="u1"),
        )
        await minimal_runner._run_hooks(
            minimal_runner._callbacks.before_agent,
            cb_ctx,
            context={},
            handler=handler,
        )
        handler.on_custom_event.assert_called_once_with("start_flow", {"source_type": "bonus"})

    @pytest.mark.asyncio
    async def test_hook_event_dispatched_to_on_step(self, minimal_runner: AgentRunner) -> None:
        handler = MagicMock()

        async def hook(ctx: CallbackContext, **kwargs: object) -> CallbackResult:
            return CallbackResult(
                event=CallbackEvent(type="step", data={"text": "phase 1"}),
            )

        minimal_runner._callbacks = RunnerCallbacks(before_agent=[hook])
        cb_ctx = CallbackContext(
            run_id="r1",
            user_input="ok",
            input_context={},
            session=SessionEntry(session_id="s1", user_id="u1"),
        )
        await minimal_runner._run_hooks(
            minimal_runner._callbacks.before_agent,
            cb_ctx,
            context={},
            handler=handler,
        )
        handler.on_step.assert_called_once_with("phase 1")


class TestLoopStateMakeResult:
    """_LoopState.make_result centralizes RunResult field population."""

    def test_make_result_includes_accumulated_metrics(self) -> None:
        tc = ToolCall(id="1", name="t", arguments={})
        ls = _LoopState(
            turns=2,
            total_tool_calls=1,
            all_tool_calls=[tc],
            all_tool_results=[],
        )
        msg = AgentMessage.assistant("done")
        out = ls.make_result(msg, stopped_by_limit=True)
        assert isinstance(out, RunResult)
        assert out.response is msg
        assert out.turns == 2
        assert out.tool_calls_count == 1
        assert out.tool_calls == [tc]
        assert out.tool_results == []
        assert out.stopped_by_limit is True
