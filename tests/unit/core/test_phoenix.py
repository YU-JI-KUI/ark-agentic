from __future__ import annotations

import importlib
import json
import sys
import types

import pytest

from ark_agentic.core.callbacks import CallbackContext
from ark_agentic.core.runner import RunResult
from ark_agentic.core.types import AgentMessage, AgentToolResult, SessionEntry, ToolCall


def test_init_phoenix_registers_without_legacy_enable_flag(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _Provider:
        pass

    provider = _Provider()

    def _register(**kwargs):
        captured.update(kwargs)
        return provider

    phoenix_pkg = types.ModuleType("phoenix")
    otel_mod = types.ModuleType("phoenix.otel")
    otel_mod.register = _register
    phoenix_pkg.otel = otel_mod

    monkeypatch.setitem(sys.modules, "phoenix", phoenix_pkg)
    monkeypatch.setitem(sys.modules, "phoenix.otel", otel_mod)
    monkeypatch.delenv("ENABLE_PHOENIX", raising=False)
    monkeypatch.delenv("PHOENIX_COLLECTOR_ENDPOINT", raising=False)
    monkeypatch.delenv("PHOENIX_PROJECT_NAME", raising=False)
    monkeypatch.delenv("PHOENIX_API_KEY", raising=False)
    monkeypatch.delenv("PHOENIX_CLIENT_HEADERS", raising=False)

    from ark_agentic.observability import phoenix

    module = importlib.reload(phoenix)
    assert module.init_phoenix(service_name="ark-agentic") is provider
    assert captured["project_name"] == "ark-agentic"


def test_init_phoenix_registers_and_shutdowns(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _Provider:
        def __init__(self) -> None:
            self.shutdown_called = False

        def shutdown(self) -> None:
            self.shutdown_called = True

    provider = _Provider()

    def _register(**kwargs):
        captured.update(kwargs)
        return provider

    phoenix_pkg = types.ModuleType("phoenix")
    otel_mod = types.ModuleType("phoenix.otel")
    otel_mod.register = _register
    phoenix_pkg.otel = otel_mod

    monkeypatch.setitem(sys.modules, "phoenix", phoenix_pkg)
    monkeypatch.setitem(sys.modules, "phoenix.otel", otel_mod)
    monkeypatch.setenv("PHOENIX_PROJECT_NAME", "ark-tests")
    monkeypatch.setenv("PHOENIX_COLLECTOR_ENDPOINT", "http://127.0.0.1:4317")

    from ark_agentic.observability import phoenix

    module = importlib.reload(phoenix)
    assert module.init_phoenix(service_name="ignored") is provider
    assert captured["project_name"] == "ark-tests"
    assert captured["endpoint"] == "http://127.0.0.1:4317"
    assert captured["auto_instrument"] is True
    assert captured["batch"] is True

    module.shutdown_phoenix()
    assert provider.shutdown_called is True

class _FakeSpan:
    def __init__(self, name: str) -> None:
        self.name = name
        self.attributes: dict[str, object] = {}
        self.ended = False
        self.status: object | None = None

    def set_attribute(self, key: str, value: object) -> None:
        self.attributes[key] = value

    def set_status(self, status: object) -> None:
        self.status = status


class _FakeSpanManager:
    def __init__(self, tracer: "_FakeTracer", span: _FakeSpan) -> None:
        self._tracer = tracer
        self._span = span

    def __enter__(self) -> _FakeSpan:
        self._tracer.events.append(("enter", self._span.name))
        return self._span

    def __exit__(self, exc_type, exc, tb) -> None:
        self._span.ended = True
        self._tracer.events.append(("exit", self._span.name))


class _FakeTracer:
    def __init__(self) -> None:
        self.spans: list[_FakeSpan] = []
        self.events: list[tuple[str, str]] = []

    def start_as_current_span(self, name: str) -> _FakeSpanManager:
        span = _FakeSpan(name)
        self.spans.append(span)
        return _FakeSpanManager(self, span)


@pytest.mark.asyncio
async def test_tracing_callbacks_capture_agent_model_and_tool_spans(monkeypatch) -> None:
    from ark_agentic.observability import tracing

    module = importlib.reload(tracing)
    tracer = _FakeTracer()
    monkeypatch.setattr(module, "get_tracer", lambda name: tracer)

    callbacks = module.create_tracing_callbacks(agent_id="insurance", agent_name="测试助手")
    ctx = CallbackContext(
        user_input="你好",
        input_context={"temp:trace_id": "trace-1"},
        session=SessionEntry(session_id="s1", user_id="u1"),
        runtime={
            "run": {
                "stream": False,
                "model": "mock-model",
                "skill_load_mode": "full",
                "agent_id": "insurance",
                "agent_name": "测试助手",
            }
        },
    )

    await callbacks.before_agent[0](ctx)

    ctx.runtime["model_phase"] = {
        "streaming": False,
        "model_override": "mock-model",
        "tool_schema_count": 1,
    }
    await callbacks.before_model[0](ctx, turn=1, messages=[{"role": "user", "content": "你好"}])
    model_response = AgentMessage.assistant("模型响应")
    model_response.metadata["finish_reason"] = "stop"
    model_response.metadata["usage"] = {"prompt_tokens": 11, "completion_tokens": 7}
    await callbacks.after_model[0](ctx, turn=1, response=model_response)

    tool_call = ToolCall(id="call_1", name="mock_tool", arguments={"k": "v"})
    await callbacks.before_tool[0](ctx, turn=1, tool_calls=[tool_call])
    await callbacks.after_tool[0](
        ctx,
        turn=1,
        results=[AgentToolResult.json_result("call_1", {"ok": True})],
    )

    ctx.runtime["run_result"] = RunResult(
        response=AgentMessage.assistant("最终答案"),
        turns=1,
        tool_calls_count=1,
        prompt_tokens=11,
        completion_tokens=7,
    )
    await callbacks.after_agent[0](ctx, response=ctx.runtime["run_result"].response)

    assert [span.name for span in tracer.spans] == [
        "insurance",
        "agent.model_phase",
        "agent.tool_phase",
        "tool.mock_tool",
    ]
    assert tracer.events == [
        ("enter", "insurance"),
        ("enter", "agent.model_phase"),
        ("exit", "agent.model_phase"),
        ("enter", "agent.tool_phase"),
        ("enter", "tool.mock_tool"),
        ("exit", "tool.mock_tool"),
        ("exit", "agent.tool_phase"),
        ("exit", "insurance"),
    ]
    assert tracer.spans[0].attributes["ark.agent_id"] == "insurance"
    assert tracer.spans[0].attributes["ark.session_id"] == "s1"
    assert tracer.spans[0].attributes["ark.trace_id"] == "trace-1"
    assert tracer.spans[0].attributes["openinference.span.kind"] == "AGENT"
    assert tracer.spans[0].attributes["session.id"] == "s1"
    assert tracer.spans[0].attributes["user.id"] == "u1"
    assert tracer.spans[0].attributes["agent.name"] == "测试助手"
    assert getattr(
        getattr(tracer.spans[0].status, "status_code", tracer.spans[0].status),
        "name",
        getattr(tracer.spans[0].status, "status_code", tracer.spans[0].status),
    ) == "OK"
    assert json.loads(tracer.spans[0].attributes["input.value"]) == {
        "user_input": "你好",
        "input_context": {"temp:trace_id": "trace-1"},
    }
    assert json.loads(tracer.spans[0].attributes["output.value"])["content"] == "最终答案"
    assert tracer.spans[1].attributes["ark.turn"] == 1
    assert tracer.spans[1].attributes["ark.message_count"] == 1
    assert tracer.spans[1].attributes["ark.finish_reason"] == "stop"
    assert tracer.spans[1].attributes["ark.prompt_tokens"] == 11
    assert tracer.spans[1].attributes["openinference.span.kind"] == "CHAIN"
    assert json.loads(tracer.spans[1].attributes["input.value"]) == {
        "messages": [{"role": "user", "content": "你好"}]
    }
    assert json.loads(tracer.spans[1].attributes["output.value"])["content"] == "模型响应"
    assert tracer.spans[2].attributes["ark.tool_count"] == 1
    assert tracer.spans[2].attributes["ark.tool_names"] == "mock_tool"
    assert tracer.spans[2].attributes["ark.result_count"] == 1
    assert tracer.spans[2].attributes["openinference.span.kind"] == "CHAIN"
    assert json.loads(tracer.spans[2].attributes["input.value"]) == [
        {"id": "call_1", "name": "mock_tool", "arguments": {"k": "v"}}
    ]
    assert json.loads(tracer.spans[2].attributes["output.value"]) == [
        {
            "tool_call_id": "call_1",
            "result_type": "json",
            "content": {"ok": True},
            "is_error": False,
            "metadata": {},
            "loop_action": "continue",
        }
    ]
    assert tracer.spans[3].attributes["openinference.span.kind"] == "TOOL"
    assert tracer.spans[3].attributes["tool.name"] == "mock_tool"
    assert json.loads(tracer.spans[3].attributes["tool.parameters"]) == {"k": "v"}
    assert json.loads(tracer.spans[3].attributes["input.value"]) == {
        "id": "call_1",
        "name": "mock_tool",
        "arguments": {"k": "v"},
    }
    assert json.loads(tracer.spans[3].attributes["output.value"]) == {
        "tool_call_id": "call_1",
        "result_type": "json",
        "content": {"ok": True},
        "is_error": False,
        "metadata": {},
        "loop_action": "continue",
    }


@pytest.mark.asyncio
async def test_tracing_callbacks_create_one_tool_span_per_tool_call(monkeypatch) -> None:
    from ark_agentic.observability import tracing

    module = importlib.reload(tracing)
    tracer = _FakeTracer()
    monkeypatch.setattr(module, "get_tracer", lambda name: tracer)

    callbacks = module.create_tracing_callbacks(agent_id="insurance", agent_name="测试助手")
    ctx = CallbackContext(
        user_input="你好",
        input_context={},
        session=SessionEntry(session_id="s3", user_id="u3"),
        runtime={},
    )

    tool_calls = [
        ToolCall(id="call_a", name="tool_a", arguments={"x": 1}),
        ToolCall(id="call_b", name="tool_b", arguments={"y": 2}),
    ]
    await callbacks.before_tool[0](ctx, turn=3, tool_calls=tool_calls)
    await callbacks.after_tool[0](
        ctx,
        turn=3,
        results=[
            AgentToolResult.json_result("call_b", {"ok": "b"}),
            AgentToolResult.json_result("call_a", {"ok": "a"}),
        ],
    )

    assert [span.name for span in tracer.spans] == [
        "agent.tool_phase",
        "tool.tool_a",
        "tool.tool_b",
    ]
    assert json.loads(tracer.spans[1].attributes["output.value"])["tool_call_id"] == "call_a"
    assert json.loads(tracer.spans[2].attributes["output.value"])["tool_call_id"] == "call_b"


@pytest.mark.asyncio
async def test_tracing_callbacks_close_pending_model_span_on_error(monkeypatch) -> None:
    from ark_agentic.core.llm.errors import LLMError, LLMErrorReason
    from ark_agentic.observability import tracing

    module = importlib.reload(tracing)
    tracer = _FakeTracer()
    monkeypatch.setattr(module, "get_tracer", lambda name: tracer)

    callbacks = module.create_tracing_callbacks(agent_id="insurance", agent_name="测试助手")
    ctx = CallbackContext(
        user_input="你好",
        input_context={},
        session=SessionEntry(session_id="s2", user_id="u2"),
        runtime={
            "run": {
                "stream": True,
                "model": "mock-model",
                "skill_load_mode": "full",
                "agent_id": "insurance",
                "agent_name": "测试助手",
            }
        },
    )

    await callbacks.before_agent[0](ctx)
    ctx.runtime["model_phase"] = {
        "streaming": True,
        "model_override": "mock-model",
        "tool_schema_count": 0,
    }
    await callbacks.before_model[0](ctx, turn=2, messages=[{"role": "user", "content": "你好"}])
    ctx.runtime["model_error"] = LLMError(
        "boom",
        reason=LLMErrorReason.TIMEOUT,
        model="mock-model",
        retryable=True,
    )
    ctx.runtime["run_result"] = RunResult(response=AgentMessage.assistant("错误兜底"))

    await callbacks.after_agent[0](ctx, response=ctx.runtime["run_result"].response)

    assert tracer.events == [
        ("enter", "insurance"),
        ("enter", "agent.model_phase"),
        ("exit", "agent.model_phase"),
        ("exit", "insurance"),
    ]
    model_span = tracer.spans[1]
    assert model_span.attributes["error"] is True
    assert model_span.attributes["ark.error_reason"] == "timeout"
