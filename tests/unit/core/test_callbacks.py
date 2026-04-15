"""Unit tests for callbacks module."""

from __future__ import annotations

from ark_agentic.core.callbacks import (
    CallbackContext,
    CallbackEvent,
    CallbackResult,
    HookAction,
    RunnerCallbacks,
    merge_runner_callbacks,
)
from ark_agentic.core.types import SessionEntry


def test_callback_context_fields() -> None:
    sess = SessionEntry(session_id="s1", user_id="u1")
    ctx = CallbackContext(
        user_input="hi",
        input_context={"k": 1},
        session=sess,
    )
    assert ctx.user_input == "hi"
    assert ctx.input_context["k"] == 1
    assert ctx.session.session_id == "s1"
    assert ctx.runtime == {}


def test_runner_callbacks_default_lists() -> None:
    rc = RunnerCallbacks()
    assert rc.before_agent == []
    assert rc.after_agent == []
    assert rc.before_model == []
    assert rc.after_model == []
    assert rc.before_tool == []
    assert rc.after_tool == []


def test_merge_runner_callbacks_preserves_order() -> None:
    async def _before_agent_a(ctx: CallbackContext) -> CallbackResult | None:
        return None

    async def _before_agent_b(ctx: CallbackContext) -> CallbackResult | None:
        return None

    async def _after_model(ctx: CallbackContext, *, turn: int, response) -> CallbackResult | None:
        return None

    merged = merge_runner_callbacks(
        RunnerCallbacks(before_agent=[_before_agent_a]),
        RunnerCallbacks(before_agent=[_before_agent_b], after_model=[_after_model]),
    )

    assert merged.before_agent == [_before_agent_a, _before_agent_b]
    assert merged.after_model == [_after_model]


def test_callback_result_defaults() -> None:
    r = CallbackResult()
    assert r.action == HookAction.PASS
    assert r.response is None
    assert r.tool_results is None
    assert r.context_updates is None
    assert r.event is None


def test_callback_event() -> None:
    e = CallbackEvent(type="intake_rejected", data={"relevant": 0})
    assert e.type == "intake_rejected"
    assert e.data == {"relevant": 0}
