"""Tests for output formatters."""

import json

import pytest

from ark_agentic.core.stream.events import AgentStreamEvent
from ark_agentic.core.stream.output_formatter import (
    AloneFormatter,
    BareAGUIFormatter,
    EnterpriseAGUIFormatter,
    LegacyInternalFormatter,
    _try_extract_json,
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
        # result is a string with multiple SSE events (reasoning_start + reasoning_message_content)
        events = [e for e in result.split("\n\n") if e.strip()]
        assert len(events) == 2
        
        # Check reasoning_start
        etype1, data1 = _parse_sse(events[0] + "\n\n")
        assert etype1 == "reasoning_start"
        assert data1["data"]["ui_protocol"] == "text"
        
        # Check reasoning_message_content (structured JSON)
        etype2, data2 = _parse_sse(events[1] + "\n\n")
        assert etype2 == "reasoning_message_content"
        dp = data2["data"]
        assert dp["ui_protocol"] == "json"
        assert dp["ui_data"] == {"think": "查询中", "content": [""]}

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
        """thinking_message_content → reasoning_start (if first) + reasoning_message_content."""
        f = EnterpriseAGUIFormatter()
        ev = _event(type="thinking_message_content", delta="分析中", message_id="m1")
        result = f.format(ev)
        events = [e for e in result.split("\n\n") if e.strip()]
        assert len(events) == 2
        etype1, _ = _parse_sse(events[0] + "\n\n")
        etype2, data2 = _parse_sse(events[1] + "\n\n")
        assert etype1 == "reasoning_start"
        assert etype2 == "reasoning_message_content"
        assert data2["data"]["ui_data"] == {"think": "", "content": ["分析中"]}

    def test_thinking_message_end_emits_reasoning_end(self) -> None:
        """thinking_message_end → reasoning_end when reasoning was active."""
        f = EnterpriseAGUIFormatter()
        f.format(_event(type="step_started", step_name="步骤"))
        ev_end = _event(type="thinking_message_end", message_id="m1")
        result = f.format(ev_end)
        etype, data = _parse_sse(result)
        assert etype == "reasoning_end"
        assert data["event"] == "reasoning_end"

    def test_step_finished_skipped(self) -> None:
        """step_finished is in _SKIP_ENTERPRISE, not emitted."""
        f = EnterpriseAGUIFormatter()
        ev = _event(type="step_finished", step_name="查询")
        result = f.format(ev)
        assert result is None

    def test_tool_call_start_skipped(self) -> None:
        """tool_call_start is in _SKIP_ENTERPRISE, not emitted."""
        f = EnterpriseAGUIFormatter()
        ev = _event(type="tool_call_start", tool_name="policy_query")
        result = f.format(ev)
        assert result is None

    def test_tool_call_result_skipped(self) -> None:
        """tool_call_result is in _SKIP_ENTERPRISE, not emitted."""
        f = EnterpriseAGUIFormatter()
        f.format(_event(type="step_started", step_name="x"))
        ev = _event(type="tool_call_result", tool_name="policy_query", tool_result="ok")
        result = f.format(ev)
        assert result is None

    def test_run_finished_emits_reasoning_end_when_active(self) -> None:
        """run_finished emits reasoning_end prefix when reasoning was active."""
        f = EnterpriseAGUIFormatter()
        f.format(_event(type="step_started", step_name="查询中"))
        ev = _event(type="run_finished", message="完成", turns=1)
        result = f.format(ev)
        parts = result.split("\n\n")
        assert any("reasoning_end" in p for p in parts)
        assert any("run_finished" in p for p in parts)

    def test_thinking_message_start_only_emits_reasoning_start(self) -> None:
        """thinking_message_start alone → reasoning_start only (no content)."""
        f = EnterpriseAGUIFormatter()
        ev = _event(type="thinking_message_start", message_id="m1")
        result = f.format(ev)
        events = [e for e in result.split("\n\n") if e.strip()]
        assert len(events) == 1
        etype, _ = _parse_sse(events[0] + "\n\n")
        assert etype == "reasoning_start"


class TestEnterpriseReasoningBeforeText:
    """Integration: reasoning phase always completes before text phase."""

    @staticmethod
    def _collect_enterprise_event_types(sse_chunks: list[str | None]) -> list[str]:
        """Extract ordered enterprise event types from formatter output."""
        types: list[str] = []
        for chunk in sse_chunks:
            if chunk is None:
                continue
            for block in chunk.split("\n\n"):
                block = block.strip()
                if not block:
                    continue
                for line in block.split("\n"):
                    if line.startswith("event: "):
                        types.append(line[7:])
        return types

    def test_step_then_text_produces_reasoning_end_before_text_start(self) -> None:
        """run_started → step_started → text_message_start must yield
        reasoning_start ... reasoning_end ... text_message_start."""
        f = EnterpriseAGUIFormatter()
        chunks = [
            f.format(_event(type="run_started", run_content="处理中")),
            f.format(_event(type="step_started", step_name="处理中")),
            f.format(_event(type="text_message_start", message_id="m1")),
            f.format(_event(type="text_message_content", delta="你好", message_id="m1")),
            f.format(_event(type="text_message_end", message_id="m1")),
            f.format(_event(type="run_finished", message="done", turns=1)),
        ]
        types = self._collect_enterprise_event_types(chunks)
        ri = types.index("reasoning_start")
        re = types.index("reasoning_end")
        ti = types.index("text_message_start")
        assert ri < re < ti

    def test_step_then_another_step_stays_in_reasoning(self) -> None:
        """Consecutive step_started events keep reasoning open (no reasoning_end between them)."""
        f = EnterpriseAGUIFormatter()
        chunks = [
            f.format(_event(type="run_started", run_content="处理中")),
            f.format(_event(type="step_started", step_name="初始")),
            f.format(_event(type="step_started", step_name="查询中")),
        ]
        types = self._collect_enterprise_event_types(chunks)
        assert types.count("reasoning_start") == 1
        assert "reasoning_end" not in types


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


class TestTryExtractJson:
    def test_plain_json_object(self) -> None:
        assert _try_extract_json('{"key": "value"}') == {"key": "value"}

    def test_plain_json_array(self) -> None:
        assert _try_extract_json("[1, 2, 3]") == [1, 2, 3]

    def test_code_fence_json(self) -> None:
        text = '```json\n{"key": "value"}\n```'
        assert _try_extract_json(text) == {"key": "value"}

    def test_code_fence_no_language_tag(self) -> None:
        text = '```\n{"items": [1]}\n```'
        assert _try_extract_json(text) == {"items": [1]}

    def test_code_fence_uppercase_json(self) -> None:
        text = '```JSON\n{"upper": true}\n```'
        assert _try_extract_json(text) == {"upper": True}

    def test_code_fence_crlf(self) -> None:
        text = '```json\r\n{"crlf": 1}\r\n```'
        assert _try_extract_json(text) == {"crlf": 1}

    def test_surrounding_whitespace(self) -> None:
        assert _try_extract_json('  \n {"a": 1} \n ') == {"a": 1}

    def test_mixed_text_returns_none(self) -> None:
        assert _try_extract_json('Here is: {"key": "value"}') is None

    def test_invalid_json_returns_none(self) -> None:
        assert _try_extract_json("{invalid json") is None

    def test_empty_string_returns_none(self) -> None:
        assert _try_extract_json("") is None

    def test_none_returns_none(self) -> None:
        # type: ignore[arg-type] — intentional None input for robustness
        assert _try_extract_json(None) is None  # type: ignore[arg-type]

    def test_plain_text_returns_none(self) -> None:
        assert _try_extract_json("Hello, world!") is None

    def test_nested_json(self) -> None:
        text = '{"a": {"b": [1, 2, {"c": true}]}}'
        result = _try_extract_json(text)
        assert result == {"a": {"b": [1, 2, {"c": True}]}}


class TestEnterpriseRunFinishedJsonDetection:
    def test_run_finished_plain_text(self) -> None:
        f = EnterpriseAGUIFormatter()
        ev = _event(type="run_finished", message="这是一段普通文本回复")
        result = f.format(ev)
        _, data = _parse_sse(result)
        dp = data["data"]
        assert dp["ui_protocol"] == "text"
        assert dp["ui_data"] == "这是一段普通文本回复"

    def test_run_finished_json_object(self) -> None:
        f = EnterpriseAGUIFormatter()
        ev = _event(type="run_finished", message='{"result": "ok", "count": 3}')
        result = f.format(ev)
        _, data = _parse_sse(result)
        dp = data["data"]
        assert dp["ui_protocol"] == "json"
        assert dp["ui_data"] == {"result": "ok", "count": 3}

    def test_run_finished_code_fenced_json(self) -> None:
        f = EnterpriseAGUIFormatter()
        msg = '```json\n{"fenced": true}\n```'
        ev = _event(type="run_finished", message=msg)
        result = f.format(ev)
        _, data = _parse_sse(result)
        dp = data["data"]
        assert dp["ui_protocol"] == "json"
        assert dp["ui_data"] == {"fenced": True}

    def test_run_finished_json_array(self) -> None:
        f = EnterpriseAGUIFormatter()
        ev = _event(type="run_finished", message='[{"id": 1}, {"id": 2}]')
        result = f.format(ev)
        _, data = _parse_sse(result)
        dp = data["data"]
        assert dp["ui_protocol"] == "json"
        assert dp["ui_data"] == [{"id": 1}, {"id": 2}]

    def test_run_finished_empty_message(self) -> None:
        f = EnterpriseAGUIFormatter()
        ev = _event(type="run_finished", message="")
        result = f.format(ev)
        _, data = _parse_sse(result)
        dp = data["data"]
        assert dp["ui_protocol"] == "text"
        assert dp["ui_data"] == ""

    def test_streaming_text_content_unaffected(self) -> None:
        """Streaming deltas must remain ui_protocol=text even if content looks like JSON."""
        f = EnterpriseAGUIFormatter()
        ev = _event(type="text_message_content", delta='{"key":')
        result = f.format(ev)
        _, data = _parse_sse(result)
        dp = data["data"]
        assert dp["ui_protocol"] == "text"
        assert dp["ui_data"] == '{"key":'


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
