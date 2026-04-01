"""Tests for ToolEvent subclass refactor + Enterprise custom event formatting.

Covers:
- ToolEvent hierarchy (CustomToolEvent, UIComponentToolEvent, StepToolEvent)
- Executor._dispatch_events isinstance dispatch + ui_protocol injection
- EnterpriseAGUIFormatter custom event: data.type + dynamic ui_protocol
- a2ui_result factory → UIComponentToolEvent
- LegacyInternalFormatter custom event backward compat
"""

import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from ark_agentic.core.types import (
    AgentToolResult,
    CustomToolEvent,
    StepToolEvent,
    ToolEvent,
    ToolLoopAction,
    ToolResultType,
    UIComponentToolEvent,
)
from ark_agentic.core.tools.executor import ToolExecutor
from ark_agentic.core.stream.events import AgentStreamEvent
from ark_agentic.core.stream.output_formatter import (
    EnterpriseAGUIFormatter,
    LegacyInternalFormatter,
)


# ============ Helpers ============


def _mock_handler() -> MagicMock:
    handler = MagicMock()
    handler.on_ui_component = MagicMock()
    handler.on_custom_event = MagicMock()
    handler.on_step = MagicMock()
    return handler


def _event(**kwargs: Any) -> AgentStreamEvent:
    defaults = {"seq": 1, "run_id": "r1", "session_id": "s1"}
    defaults.update(kwargs)
    return AgentStreamEvent(**defaults)


def _parse_sse(sse: str) -> tuple[str, dict]:
    event_type = ""
    data_json = ""
    for line in sse.strip().split("\n"):
        if line.startswith("event: "):
            event_type = line[7:]
        elif line.startswith("data: "):
            data_json = line[6:]
    return event_type, json.loads(data_json)


# ============ ToolEvent Hierarchy ============


class TestToolEventHierarchy:
    def test_custom_tool_event_is_tool_event(self) -> None:
        evt = CustomToolEvent(custom_type="start_flow", payload={"k": "v"})
        assert isinstance(evt, ToolEvent)

    def test_ui_component_tool_event_is_tool_event(self) -> None:
        evt = UIComponentToolEvent(component={"template": "card"})
        assert isinstance(evt, ToolEvent)

    def test_step_tool_event_is_tool_event(self) -> None:
        evt = StepToolEvent(text="处理中")
        assert isinstance(evt, ToolEvent)

    def test_custom_tool_event_fields(self) -> None:
        evt = CustomToolEvent(custom_type="start_flow", payload={"flow_type": "E027Flow"})
        assert evt.custom_type == "start_flow"
        assert evt.payload == {"flow_type": "E027Flow"}

    def test_custom_tool_event_defaults(self) -> None:
        evt = CustomToolEvent()
        assert evt.custom_type == ""
        assert evt.payload == {}

    def test_ui_component_tool_event_fields(self) -> None:
        evt = UIComponentToolEvent(component={"template": "card", "data": {}})
        assert evt.component == {"template": "card", "data": {}}

    def test_step_tool_event_fields(self) -> None:
        evt = StepToolEvent(text="查询中")
        assert evt.text == "查询中"

    def test_events_list_accepts_mixed_subclasses(self) -> None:
        events: list[ToolEvent] = [
            CustomToolEvent(custom_type="x"),
            UIComponentToolEvent(component={}),
            StepToolEvent(text="y"),
        ]
        assert len(events) == 3
        assert isinstance(events[0], CustomToolEvent)
        assert isinstance(events[1], UIComponentToolEvent)
        assert isinstance(events[2], StepToolEvent)


# ============ a2ui_result Factory ============


class TestA2UIResultFactory:
    def test_a2ui_result_creates_ui_component_events(self) -> None:
        result = AgentToolResult.a2ui_result("tc1", {"template": "card"})
        assert result.result_type == ToolResultType.A2UI
        assert len(result.events) == 1
        evt = result.events[0]
        assert isinstance(evt, UIComponentToolEvent)
        assert evt.component == {"template": "card"}

    def test_a2ui_result_multiple_components(self) -> None:
        components = [{"template": "a"}, {"template": "b"}]
        result = AgentToolResult.a2ui_result("tc1", components)
        assert len(result.events) == 2
        assert all(isinstance(e, UIComponentToolEvent) for e in result.events)
        assert result.events[0].component == {"template": "a"}
        assert result.events[1].component == {"template": "b"}


# ============ Executor Dispatch ============


class TestExecutorDispatch:
    def test_dispatch_ui_component(self) -> None:
        handler = _mock_handler()
        result = AgentToolResult.a2ui_result("tc1", {"card": "x"})
        ToolExecutor._dispatch_events(result, handler)
        handler.on_ui_component.assert_called_once_with({"card": "x"})

    def test_dispatch_custom_event_with_json_protocol(self) -> None:
        handler = _mock_handler()
        result = AgentToolResult.json_result(
            "tc1", {"msg": "ok"},
            events=[CustomToolEvent(custom_type="start_flow", payload={"flow_type": "E027Flow"})],
        )
        ToolExecutor._dispatch_events(result, handler)
        handler.on_custom_event.assert_called_once()
        args = handler.on_custom_event.call_args
        assert args[0][0] == "start_flow"
        payload = args[0][1]
        assert payload["flow_type"] == "E027Flow"
        assert payload["ui_protocol"] == "json"

    def test_dispatch_custom_event_with_text_protocol(self) -> None:
        handler = _mock_handler()
        result = AgentToolResult.text_result(
            "tc1", "ok",
            events=[CustomToolEvent(custom_type="notify", payload={"msg": "done"})],
        )
        ToolExecutor._dispatch_events(result, handler)
        args = handler.on_custom_event.call_args
        assert args[0][1]["ui_protocol"] == "text"

    def test_dispatch_custom_event_with_a2ui_protocol(self) -> None:
        handler = _mock_handler()
        result = AgentToolResult.a2ui_result(
            "tc1", {"template": "card"},
            events=[CustomToolEvent(custom_type="extra", payload={"data": 1})],
        )
        ToolExecutor._dispatch_events(result, handler)
        custom_calls = [c for c in handler.on_custom_event.call_args_list]
        assert len(custom_calls) == 1
        assert custom_calls[0][0][1]["ui_protocol"] == "A2UI"

    def test_dispatch_step_event(self) -> None:
        handler = _mock_handler()
        result = AgentToolResult.text_result(
            "tc1", "ok",
            events=[StepToolEvent(text="处理中…")],
        )
        ToolExecutor._dispatch_events(result, handler)
        handler.on_step.assert_called_once_with("处理中…")

    def test_dispatch_no_handler(self) -> None:
        result = AgentToolResult.json_result(
            "tc1", {},
            events=[CustomToolEvent(custom_type="x")],
        )
        ToolExecutor._dispatch_events(result, None)

    def test_dispatch_no_events(self) -> None:
        handler = _mock_handler()
        result = AgentToolResult.text_result("tc1", "ok")
        ToolExecutor._dispatch_events(result, handler)
        handler.on_custom_event.assert_not_called()
        handler.on_ui_component.assert_not_called()
        handler.on_step.assert_not_called()

    def test_dispatch_preserves_payload_fields(self) -> None:
        handler = _mock_handler()
        payload = {"flow_type": "E027Flow", "query_msg": "保单号-P001，金额-1000"}
        result = AgentToolResult.json_result(
            "tc1", {},
            events=[CustomToolEvent(custom_type="start_flow", payload=payload)],
        )
        ToolExecutor._dispatch_events(result, handler)
        sent = handler.on_custom_event.call_args[0][1]
        assert sent["flow_type"] == "E027Flow"
        assert sent["query_msg"] == "保单号-P001，金额-1000"
        assert sent["ui_protocol"] == "json"

    def test_dispatch_does_not_mutate_original_payload(self) -> None:
        handler = _mock_handler()
        original = {"flow_type": "E027Flow"}
        evt = CustomToolEvent(custom_type="start_flow", payload=original)
        result = AgentToolResult.json_result("tc1", {}, events=[evt])
        ToolExecutor._dispatch_events(result, handler)
        assert "ui_protocol" not in original


# ============ Enterprise Formatter: Custom Event ============


class TestEnterpriseCustomEvent:
    def test_custom_event_has_type_and_ui_protocol(self) -> None:
        f = EnterpriseAGUIFormatter()
        ev = _event(
            type="custom",
            custom_type="start_flow",
            custom_data={"ui_protocol": "json", "flow_type": "E027Flow", "query_msg": "xxx"},
        )
        result = f.format(ev)
        _, data = _parse_sse(result)
        dp = data["data"]
        assert dp["type"] == "start_flow"
        assert dp["ui_protocol"] == "json"
        assert dp["ui_data"] == {"flow_type": "E027Flow", "query_msg": "xxx"}

    def test_custom_event_ui_protocol_stripped_from_ui_data(self) -> None:
        f = EnterpriseAGUIFormatter()
        ev = _event(
            type="custom",
            custom_type="start_flow",
            custom_data={"ui_protocol": "json", "key": "val"},
        )
        result = f.format(ev)
        _, data = _parse_sse(result)
        dp = data["data"]
        assert "ui_protocol" not in (dp["ui_data"] or {})
        assert dp["ui_data"] == {"key": "val"}

    def test_custom_event_fallback_json_when_no_ui_protocol(self) -> None:
        f = EnterpriseAGUIFormatter()
        ev = _event(
            type="custom",
            custom_type="intake_rejected",
            custom_data={"relevant": 0},
        )
        result = f.format(ev)
        _, data = _parse_sse(result)
        dp = data["data"]
        assert dp["type"] == "intake_rejected"
        assert dp["ui_protocol"] == "json"
        assert dp["ui_data"] == {"relevant": 0}

    def test_custom_event_text_ui_protocol(self) -> None:
        f = EnterpriseAGUIFormatter()
        ev = _event(
            type="custom",
            custom_type="notify",
            custom_data={"ui_protocol": "text", "message": "hello"},
        )
        result = f.format(ev)
        _, data = _parse_sse(result)
        dp = data["data"]
        assert dp["ui_protocol"] == "text"
        assert dp["ui_data"] == {"message": "hello"}

    def test_custom_event_empty_custom_data(self) -> None:
        f = EnterpriseAGUIFormatter()
        ev = _event(type="custom", custom_type="ping", custom_data={})
        result = f.format(ev)
        _, data = _parse_sse(result)
        dp = data["data"]
        assert dp["type"] == "ping"
        assert dp["ui_protocol"] == "json"

    def test_custom_event_none_custom_data(self) -> None:
        f = EnterpriseAGUIFormatter()
        ev = _event(type="custom", custom_type="ping", custom_data=None)
        result = f.format(ev)
        _, data = _parse_sse(result)
        dp = data["data"]
        assert dp["type"] == "ping"
        assert dp["ui_protocol"] == "json"

    def test_non_custom_event_has_no_type_field(self) -> None:
        f = EnterpriseAGUIFormatter()
        ev = _event(type="run_started", run_content="开始")
        result = f.format(ev)
        _, data = _parse_sse(result)
        dp = data["data"]
        assert "type" not in dp

    def test_full_enterprise_envelope_structure(self) -> None:
        f = EnterpriseAGUIFormatter(source_bu_type="shouxian", app_type="jgj")
        ev = _event(
            type="custom",
            custom_type="start_flow",
            custom_data={"ui_protocol": "json", "flow_type": "E027Flow", "query_msg": "保单号-P001，金额-5000"},
        )
        result = f.format(ev)
        _, envelope = _parse_sse(result)

        assert envelope["protocol"] == "AGUI"
        assert envelope["event"] == "custom"
        assert envelope["source_bu_type"] == "shouxian"
        assert envelope["app_type"] == "jgj"

        dp = envelope["data"]
        assert dp["type"] == "start_flow"
        assert dp["code"] == "200"
        assert dp["ui_protocol"] == "json"
        assert dp["ui_data"] == {"flow_type": "E027Flow", "query_msg": "保单号-P001，金额-5000"}
        assert "timestamp" in dp


# ============ Legacy Internal Formatter: Custom Event Compat ============


class TestLegacyInternalCustomEvent:
    def test_custom_event_maps_to_ui_component(self) -> None:
        f = LegacyInternalFormatter()
        ev = _event(type="custom", custom_type="start_flow", custom_data={"flow_type": "E027Flow"})
        result = f.format(ev)
        etype, data = _parse_sse(result)
        assert etype == "response.ui.component"
        assert data["ui_component"] == {"flow_type": "E027Flow"}


# ============ End-to-End: Tool → Executor → Formatter ============


class TestEndToEndCustomEvent:
    def test_json_result_custom_event_produces_correct_enterprise_output(self) -> None:
        handler = _mock_handler()
        result = AgentToolResult.json_result(
            "tc1",
            {"message": "已提交办理请求"},
            loop_action=ToolLoopAction.STOP,
            events=[
                CustomToolEvent(
                    custom_type="start_flow",
                    payload={"flow_type": "E027Flow", "query_msg": "保单号-P001，金额-5000"},
                ),
            ],
        )

        ToolExecutor._dispatch_events(result, handler)

        custom_type, custom_data = handler.on_custom_event.call_args[0]
        assert custom_type == "start_flow"
        assert custom_data["ui_protocol"] == "json"
        assert custom_data["flow_type"] == "E027Flow"

        ev = _event(type="custom", custom_type=custom_type, custom_data=custom_data)
        f = EnterpriseAGUIFormatter(source_bu_type="shouxian")
        sse = f.format(ev)
        _, envelope = _parse_sse(sse)
        dp = envelope["data"]

        assert dp["type"] == "start_flow"
        assert dp["ui_protocol"] == "json"
        assert dp["ui_data"] == {"flow_type": "E027Flow", "query_msg": "保单号-P001，金额-5000"}

    def test_text_result_custom_event_gets_text_protocol(self) -> None:
        handler = _mock_handler()
        result = AgentToolResult.text_result(
            "tc1", "ok",
            events=[CustomToolEvent(custom_type="status", payload={"ready": True})],
        )
        ToolExecutor._dispatch_events(result, handler)
        _, custom_data = handler.on_custom_event.call_args[0]

        ev = _event(type="custom", custom_type="status", custom_data=custom_data)
        f = EnterpriseAGUIFormatter()
        sse = f.format(ev)
        _, envelope = _parse_sse(sse)
        dp = envelope["data"]

        assert dp["type"] == "status"
        assert dp["ui_protocol"] == "text"
        assert dp["ui_data"] == {"ready": True}
