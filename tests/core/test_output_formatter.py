"""Tests for output formatters."""

import json

import pytest

from ark_agentic.core.stream.events import AgentStreamEvent
from ark_agentic.core.stream.output_formatter import (
    AloneFormatter,
    BareAGUIFormatter,
    EnterpriseAGUIFormatter,
    LegacyInternalFormatter,
    create_formatter,
)


def _event(**kwargs) -> AgentStreamEvent:
    defaults = {"seq": 1, "run_id": "r1", "session_id": "s1"}
    defaults.update(kwargs)
    return AgentStreamEvent(**defaults)


def _parse_sse(sse: str) -> tuple[str, dict]:
    """Parse SSE string → (event_type, data_dict)."""
    event_type = ""
    data_json = ""
    for line in sse.strip().split("\n"):
        if line.startswith("event: "):
            event_type = line[7:]
        elif line.startswith("data: "):
            data_json = line[6:]
    return event_type, json.loads(data_json)


class TestBareAGUIFormatter:
    def test_run_started(self) -> None:
        f = BareAGUIFormatter()
        ev = _event(type="run_started", run_content="开始")
        result = f.format(ev)
        etype, data = _parse_sse(result)
        assert etype == "run_started"
        assert data["type"] == "run_started"
        assert data["run_content"] == "开始"

    def test_text_message_content(self) -> None:
        f = BareAGUIFormatter()
        ev = _event(type="text_message_content", delta="hello")
        result = f.format(ev)
        _, data = _parse_sse(result)
        assert data["delta"] == "hello"


class TestLegacyInternalFormatter:
    def test_run_started_maps_to_response_created(self) -> None:
        f = LegacyInternalFormatter()
        ev = _event(type="run_started", run_content="开始")
        result = f.format(ev)
        etype, data = _parse_sse(result)
        assert etype == "response.created"
        assert data["content"] == "开始"

    def test_step_started_maps_to_response_step(self) -> None:
        f = LegacyInternalFormatter()
        ev = _event(type="step_started", step_name="查询中")
        result = f.format(ev)
        etype, data = _parse_sse(result)
        assert etype == "response.step"
        assert data["content"] == "查询中"

    def test_text_message_content_maps_to_content_delta(self) -> None:
        f = LegacyInternalFormatter()
        ev = _event(type="text_message_content", delta="Hi")
        result = f.format(ev)
        etype, data = _parse_sse(result)
        assert etype == "response.content.delta"
        assert data["delta"] == "Hi"
        assert data["turn"] == 1  # default 1-based ReAct turn when not set

    def test_text_message_content_includes_turn(self) -> None:
        f = LegacyInternalFormatter()
        ev = _event(type="text_message_content", delta="ok", turn=2)
        result = f.format(ev)
        etype, data = _parse_sse(result)
        assert etype == "response.content.delta"
        assert data["turn"] == 2

    def test_run_finished_maps_to_response_completed(self) -> None:
        f = LegacyInternalFormatter()
        ev = _event(type="run_finished", message="done", turns=2, usage={"prompt_tokens": 10, "completion_tokens": 5})
        result = f.format(ev)
        etype, data = _parse_sse(result)
        assert etype == "response.completed"
        assert data["message"] == "done"
        assert data["turns"] == 2

    def test_run_error_maps_to_response_failed(self) -> None:
        f = LegacyInternalFormatter()
        ev = _event(type="run_error", error_message="boom")
        result = f.format(ev)
        etype, data = _parse_sse(result)
        assert etype == "response.failed"
        assert data["error_message"] == "boom"

    def test_step_finished_maps_to_response_step_done(self) -> None:
        f = LegacyInternalFormatter()
        ev = _event(type="step_finished", step_name="查询完成")
        result = f.format(ev)
        etype, data = _parse_sse(result)
        # Must be step.done, NOT step — otherwise frontend creates a new step element
        assert etype == "response.step.done"
        assert data["content"] == "查询完成"

    def test_text_message_start_skipped(self) -> None:
        f = LegacyInternalFormatter()
        ev = _event(type="text_message_start")
        assert f.format(ev) is None

    def test_tool_call_args_skipped(self) -> None:
        f = LegacyInternalFormatter()
        ev = _event(type="tool_call_args")
        assert f.format(ev) is None

    def test_custom_maps_to_ui_component(self) -> None:
        f = LegacyInternalFormatter()
        ev = _event(type="text_message_content", content_kind="a2ui", custom_data={"card": "x"})
        result = f.format(ev)
        etype, data = _parse_sse(result)
        assert etype == "response.ui.component"
        assert data["ui_component"] == {"card": "x"}


class TestEnterpriseAGUIFormatter:
    def test_envelope_structure(self) -> None:
        f = EnterpriseAGUIFormatter(source_bu_type="shouxian", app_type="jgj")
        ev = _event(type="run_started", run_content="开始")
        result = f.format(ev)
        _, data = _parse_sse(result)
        assert data["protocol"] == "AGUI"
        assert data["source_bu_type"] == "shouxian"
        assert data["app_type"] == "jgj"
        assert data["event"] == "run_started"
        assert "data" in data

    def test_run_started_ui_data_not_none(self) -> None:
        f = EnterpriseAGUIFormatter()
        ev = _event(type="run_started", run_content="初始化")
        result = f.format(ev)
        _, data = _parse_sse(result)
        dp = data["data"]
        assert dp["ui_protocol"] == "text"
        assert dp["ui_data"] == "初始化"

    def test_step_started_ui_protocol_json(self) -> None:
        f = EnterpriseAGUIFormatter()
        ev = _event(type="step_started", step_name="查询中")
        result = f.format(ev)
        # result is a string with multiple SSE events (REASONING_START + REASONING_MESSAGE_CONTENT)
        events = [e for e in result.split("\n\n") if e.strip()]
        assert len(events) == 2
        
        # Check REASONING_START
        etype1, data1 = _parse_sse(events[0] + "\n\n")
        assert etype1 == "REASONING_START"
        assert data1["data"]["ui_protocol"] == "text"
        
        # Check REASONING_MESSAGE_CONTENT
        etype2, data2 = _parse_sse(events[1] + "\n\n")
        assert etype2 == "REASONING_MESSAGE_CONTENT"
        dp = data2["data"]
        assert dp["ui_protocol"] == "text"
        assert dp["ui_data"] == "\n查询中\n"

    def test_text_content_ui_protocol_text(self) -> None:
        f = EnterpriseAGUIFormatter()
        ev = _event(type="text_message_content", delta="你好")
        result = f.format(ev)
        _, data = _parse_sse(result)
        dp = data["data"]
        assert dp["ui_protocol"] == "text"
        assert dp["ui_data"] == "你好"

    def test_custom_a2ui_protocol(self) -> None:
        f = EnterpriseAGUIFormatter()
        ev = _event(type="text_message_content", content_kind="a2ui", custom_data={"card": "demo"})
        result = f.format(ev)
        etype, data = _parse_sse(result)
        assert etype == "text_message_content"
        dp = data["data"]
        assert dp["ui_protocol"] == "A2UI"
        assert dp["ui_data"] == {"card": "demo"}

    def test_message_id_from_event_not_run_id(self) -> None:
        """message_id must come from event.message_id (text lifecycle), not run_id."""
        f = EnterpriseAGUIFormatter()
        ev = _event(type="text_message_content", delta="hi", message_id="msg-123")
        result = f.format(ev)
        _, data = _parse_sse(result)
        dp = data["data"]
        assert dp.get("message_id") == "msg-123"

    def test_step_started_no_message_id_in_data(self) -> None:
        """Non-text events should not carry a message_id."""
        f = EnterpriseAGUIFormatter()
        ev = _event(type="step_started", step_name="查询中")
        result = f.format(ev)
        events = [e for e in result.split("\n\n") if e.strip()]
        _, data = _parse_sse(events[-1] + "\n\n")
        dp = data["data"]
        assert dp.get("message_id") is None

    def test_thinking_message_content_maps_to_reasoning_message_content(self) -> None:
        """thinking_message_content → REASONING_START (if first) + REASONING_MESSAGE_CONTENT."""
        f = EnterpriseAGUIFormatter()
        ev = _event(type="thinking_message_content", delta="分析中", message_id="m1")
        result = f.format(ev)
        events = [e for e in result.split("\n\n") if e.strip()]
        assert len(events) == 2
        etype1, _ = _parse_sse(events[0] + "\n\n")
        etype2, data2 = _parse_sse(events[1] + "\n\n")
        assert etype1 == "REASONING_START"
        assert etype2 == "REASONING_MESSAGE_CONTENT"
        assert data2["data"]["ui_data"] == "分析中"

    def test_thinking_message_end_emits_reasoning_end(self) -> None:
        """thinking_message_end → REASONING_END when reasoning was active."""
        f = EnterpriseAGUIFormatter()
        f.format(_event(type="step_started", step_name="步骤"))
        ev_end = _event(type="thinking_message_end", message_id="m1")
        result = f.format(ev_end)
        etype, data = _parse_sse(result)
        assert etype == "REASONING_END"
        assert data["event"] == "REASONING_END"

    def test_step_finished_maps_to_reasoning_message_content(self) -> None:
        """step_finished → REASONING_MESSAGE_CONTENT with '完成' suffix."""
        f = EnterpriseAGUIFormatter()
        ev = _event(type="step_finished", step_name="查询")
        result = f.format(ev)
        events = [e for e in result.split("\n\n") if e.strip()]
        _, data = _parse_sse(events[-1] + "\n\n")
        assert data["event"] == "REASONING_MESSAGE_CONTENT"
        assert "查询" in data["data"]["ui_data"]
        assert "完成" in data["data"]["ui_data"]

    def test_tool_call_start_maps_to_reasoning_message_content(self) -> None:
        """tool_call_start → REASONING_START + REASONING_MESSAGE_CONTENT."""
        f = EnterpriseAGUIFormatter()
        ev = _event(type="tool_call_start", tool_name="policy_query")
        result = f.format(ev)
        events = [e for e in result.split("\n\n") if e.strip()]
        assert len(events) == 2
        _, data = _parse_sse(events[1] + "\n\n")
        assert data["event"] == "REASONING_MESSAGE_CONTENT"
        assert "policy_query" in data["data"]["ui_data"]

    def test_tool_call_result_maps_to_reasoning_message_content(self) -> None:
        """tool_call_result → REASONING_MESSAGE_CONTENT."""
        f = EnterpriseAGUIFormatter()
        f.format(_event(type="step_started", step_name="x"))
        ev = _event(type="tool_call_result", tool_name="policy_query", tool_result="ok")
        result = f.format(ev)
        events = [e for e in result.split("\n\n") if e.strip()]
        _, data = _parse_sse(events[-1] + "\n\n")
        assert data["event"] == "REASONING_MESSAGE_CONTENT"
        assert "policy_query" in data["data"]["ui_data"]
        assert "完成" in data["data"]["ui_data"]

    def test_run_finished_emits_reasoning_end_when_active(self) -> None:
        """run_finished emits REASONING_END prefix when reasoning was active."""
        f = EnterpriseAGUIFormatter()
        f.format(_event(type="step_started", step_name="查询中"))
        ev = _event(type="run_finished", message="完成", turns=1)
        result = f.format(ev)
        parts = result.split("\n\n")
        assert any("REASONING_END" in p for p in parts)
        assert any("run_finished" in p for p in parts)

    def test_thinking_message_start_only_emits_reasoning_start(self) -> None:
        """thinking_message_start alone → REASONING_START only (no content)."""
        f = EnterpriseAGUIFormatter()
        ev = _event(type="thinking_message_start", message_id="m1")
        result = f.format(ev)
        events = [e for e in result.split("\n\n") if e.strip()]
        assert len(events) == 1
        etype, _ = _parse_sse(events[0] + "\n\n")
        assert etype == "REASONING_START"


class TestAloneFormatter:
    def test_run_started_maps_to_sa_ready(self) -> None:
        f = AloneFormatter()
        ev = _event(type="run_started")
        result = f.format(ev)
        etype, data = _parse_sse(result)
        assert etype == "sa_ready"
        assert data["status"] == "ready"

    def test_text_content_maps_to_sa_stream_chunk(self) -> None:
        f = AloneFormatter()
        ev = _event(type="text_message_content", delta="hello")
        result = f.format(ev)
        etype, data = _parse_sse(result)
        assert etype == "sa_stream_chunk"
        assert data["content"] == "hello"
        assert data["turn"] == 1  # default 1-based ReAct turn

    def test_step_started_maps_to_sa_stream_think(self) -> None:
        f = AloneFormatter()
        ev = _event(type="step_started", step_name="思考中")
        result = f.format(ev)
        etype, data = _parse_sse(result)
        assert etype == "sa_stream_think"
        assert data["thought"] == "思考中"

    def test_run_finished_maps_to_sa_stream_complete_and_sa_done(self) -> None:
        f = AloneFormatter()
        ev = _event(type="run_finished", message="完成")
        result = f.format(ev)
        assert result is not None
        # Should contain both sa_stream_complete and sa_done
        assert "event: sa_stream_complete" in result
        assert "event: sa_done" in result
        # Parse the first SSE block
        etype, data = _parse_sse(result.split("\n\n")[0] + "\n\n")
        assert etype == "sa_stream_complete"
        assert data["content"] == "完成"

    def test_run_error_maps_to_sa_error(self) -> None:
        f = AloneFormatter()
        ev = _event(type="run_error", error_message="fail")
        result = f.format(ev)
        etype, data = _parse_sse(result)
        assert etype == "sa_error"
        assert data["code"] == 500

    def test_tool_call_start_skipped(self) -> None:
        f = AloneFormatter()
        ev = _event(type="tool_call_start")
        assert f.format(ev) is None

    def test_custom_skipped(self) -> None:
        f = AloneFormatter()
        ev = _event(type="custom")
        assert f.format(ev) is None


class TestCreateFormatter:
    def test_default_is_internal(self) -> None:
        f = create_formatter()
        assert isinstance(f, LegacyInternalFormatter)

    def test_agui(self) -> None:
        f = create_formatter("agui")
        assert isinstance(f, BareAGUIFormatter)

    def test_enterprise(self) -> None:
        f = create_formatter("enterprise", source_bu_type="chanxian", app_type="hcz")
        assert isinstance(f, EnterpriseAGUIFormatter)

    def test_alone(self) -> None:
        f = create_formatter("alone")
        assert isinstance(f, AloneFormatter)

    def test_unknown_falls_back_to_internal(self) -> None:
        f = create_formatter("unknown_proto")
        assert isinstance(f, LegacyInternalFormatter)
