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
        _, data = _parse_sse(result)
        dp = data["data"]
        assert dp["ui_protocol"] == "json"
        assert dp["ui_data"]["think"] == "查询中"
        assert dp["ui_data"]["think_status"] == 1

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
        _, data = _parse_sse(result)
        dp = data["data"]
        assert dp.get("message_id") is None


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
