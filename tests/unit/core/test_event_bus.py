"""Tests for StreamEventBus AG-UI lifecycle management."""

import asyncio

import pytest

from ark_agentic.core.stream.event_bus import StreamEventBus
from ark_agentic.core.stream.events import AgentStreamEvent


def _make_bus() -> tuple[StreamEventBus, asyncio.Queue[AgentStreamEvent]]:
    queue: asyncio.Queue[AgentStreamEvent] = asyncio.Queue()
    bus = StreamEventBus(run_id="r1", session_id="s1", queue=queue)
    return bus, queue


def _drain(queue: asyncio.Queue[AgentStreamEvent]) -> list[AgentStreamEvent]:
    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    return events


class TestStreamEventBusLifecycle:
    """Test step/text lifecycle auto-pairing."""

    def test_emit_created_produces_run_started(self) -> None:
        bus, q = _make_bus()
        bus.emit_created("开始处理")
        events = _drain(q)
        assert len(events) == 1
        assert events[0].type == "run_started"
        assert events[0].run_content == "开始处理"
        assert events[0].step_name is None  # run_started must not pollute step field

    def test_on_step_emits_step_started(self) -> None:
        bus, q = _make_bus()
        bus.on_step("正在查询保单…")
        events = _drain(q)
        assert len(events) == 1
        assert events[0].type == "step_started"
        assert events[0].step_name == "正在查询保单…"

    def test_consecutive_steps_auto_close_previous(self) -> None:
        bus, q = _make_bus()
        bus.on_step("步骤一")
        bus.on_step("步骤二")
        events = _drain(q)
        assert len(events) == 3
        assert events[0].type == "step_started"
        assert events[0].step_name == "步骤一"
        assert events[1].type == "step_finished"
        assert events[1].step_name == "步骤一"
        assert events[2].type == "step_started"
        assert events[2].step_name == "步骤二"

    def test_emit_completed_closes_active_step_and_text(self) -> None:
        bus, q = _make_bus()
        bus.on_step("查询中")
        bus.on_content_delta("Hello")
        _ = _drain(q)

        bus.emit_completed(message="done", turns=1)
        events = _drain(q)
        types = [e.type for e in events]
        assert "text_message_end" in types
        assert "step_finished" in types
        assert types[-1] == "run_finished"

    def test_emit_failed_closes_active_step(self) -> None:
        bus, q = _make_bus()
        bus.on_step("处理中")
        _ = _drain(q)

        bus.emit_failed("boom")
        events = _drain(q)
        types = [e.type for e in events]
        assert "step_finished" in types
        assert types[-1] == "run_error"
        assert events[-1].error_message == "boom"

    def test_empty_step_ignored(self) -> None:
        bus, q = _make_bus()
        bus.on_step("")
        assert q.empty()

    def test_empty_delta_ignored(self) -> None:
        bus, q = _make_bus()
        bus.on_content_delta("")
        assert q.empty()


class TestStreamEventBusTextMessage:
    """Test text_message auto-start/end."""

    def test_content_delta_auto_starts_text_message(self) -> None:
        bus, q = _make_bus()
        bus.on_content_delta("Hi")
        events = _drain(q)
        assert len(events) == 2
        assert events[0].type == "text_message_start"
        assert events[0].message_id is not None
        assert events[1].type == "text_message_content"
        assert events[1].delta == "Hi"
        assert events[1].turn == 1  # default 1-based ReAct turn

    def test_multiple_deltas_share_message_id(self) -> None:
        bus, q = _make_bus()
        bus.on_content_delta("A")
        bus.on_content_delta("B")
        events = _drain(q)
        start_id = events[0].message_id
        assert events[2].message_id == start_id


class TestStreamEventBusToolCalls:
    """Test tool call event emission with tool_call_id."""

    def test_tool_call_start_emits_start_and_args(self) -> None:
        bus, q = _make_bus()
        bus.on_tool_call_start("tc_1", "policy_query", {"id": "P001"})
        events = _drain(q)
        assert len(events) == 2
        assert events[0].type == "tool_call_start"
        assert events[0].tool_call_id == "tc_1"
        assert events[0].tool_name == "policy_query"
        assert events[1].type == "tool_call_args"
        assert events[1].tool_args == {"id": "P001"}

    def test_tool_call_result_emits_end_and_result(self) -> None:
        bus, q = _make_bus()
        bus.on_tool_call_result("tc_1", "policy_query", "found")
        events = _drain(q)
        assert len(events) == 2
        assert events[0].type == "tool_call_end"
        assert events[0].tool_call_id == "tc_1"
        assert events[1].type == "tool_call_result"
        assert events[1].tool_result == "found"

    def test_tool_result_truncation(self) -> None:
        bus, q = _make_bus()
        long_result = "x" * 3000
        bus.on_tool_call_result("tc_1", "t", long_result)
        events = _drain(q)
        result_event = events[1]
        assert len(str(result_event.tool_result)) < 2100


class TestStreamEventBusThinkingDelta:
    """Test on_thinking_delta → thinking_message_start + thinking_message_content."""

    def test_thinking_delta_emits_start_then_content(self) -> None:
        bus, q = _make_bus()
        bus.on_thinking_delta("推理内容", turn=1)
        events = _drain(q)
        assert len(events) == 2
        assert events[0].type == "thinking_message_start"
        assert events[0].message_id is not None
        assert events[1].type == "thinking_message_content"
        assert events[1].delta == "推理内容"
        assert events[1].turn == 1
        assert events[1].message_id == events[0].message_id

    def test_multiple_thinking_deltas_share_message_id(self) -> None:
        bus, q = _make_bus()
        bus.on_thinking_delta("A", turn=1)
        bus.on_thinking_delta("B", turn=1)
        events = _drain(q)
        start_ev = next(e for e in events if e.type == "thinking_message_start")
        content_evs = [e for e in events if e.type == "thinking_message_content"]
        assert all(e.message_id == start_ev.message_id for e in content_evs)

    def test_emit_completed_closes_thinking_message(self) -> None:
        bus, q = _make_bus()
        bus.on_thinking_delta("思考", turn=1)
        _ = _drain(q)
        bus.emit_completed(message="done", turns=1)
        events = _drain(q)
        types = [e.type for e in events]
        assert "thinking_message_end" in types
        assert "run_finished" in types

    def test_empty_thinking_delta_ignored(self) -> None:
        bus, q = _make_bus()
        bus.on_thinking_delta("", turn=1)
        assert q.empty()


class TestStreamEventBusUIComponent:
    """Test A2UI event emission (text_message_content + content_kind=a2ui)."""

    def test_on_ui_component(self) -> None:
        bus, q = _make_bus()
        bus.on_ui_component({"card": "demo"})
        events = _drain(q)
        assert len(events) == 1
        assert events[0].type == "text_message_content"
        assert events[0].content_kind == "a2ui"
        assert events[0].custom_data == {"card": "demo"}


class TestStreamEventBusRunContent:
    """run_started uses run_content, not step_name."""

    def test_run_started_uses_run_content_field(self) -> None:
        bus, q = _make_bus()
        bus.emit_created("初始化中")
        events = _drain(q)
        ev = events[0]
        assert ev.run_content == "初始化中"
        assert ev.step_name is None


class TestStreamEventBusSequencing:
    """Test seq numbering."""

    def test_seq_monotonically_increases(self) -> None:
        bus, q = _make_bus()
        bus.emit_created()
        bus.on_step("s1")
        bus.on_content_delta("x")
        events = _drain(q)
        seqs = [e.seq for e in events]
        assert seqs == sorted(seqs)
        assert len(set(seqs)) == len(seqs)
