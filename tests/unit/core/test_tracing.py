"""Tests for the runner observability layer (decorators + provider registry).

Uses ``InMemorySpanExporter`` so we can assert on real OTel spans without
hitting any backend. OTel only allows one global TracerProvider per process,
so we install one TracerProvider at module load and clear the exporter
between tests.
"""

from __future__ import annotations

import pytest
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from opentelemetry.sdk.trace.sampling import ALWAYS_ON

from ark_agentic.core.observability import (
    add_span_attributes,
    add_span_input,
    add_span_output,
    setup_tracing_from_env,
    shutdown_tracing,
    traced_agent,
    traced_chain,
    traced_tool,
)
from ark_agentic.core.observability.providers import PROVIDERS


# ---------------- One-shot TracerProvider for this module ----------------

_EXPORTER = InMemorySpanExporter()
_TP = TracerProvider(
    sampler=ALWAYS_ON,
    resource=Resource.create({"service.name": "ark-agentic-test"}),
)
_TP.add_span_processor(SimpleSpanProcessor(_EXPORTER))
trace.set_tracer_provider(_TP)


@pytest.fixture
def in_memory_exporter() -> InMemorySpanExporter:
    """Yield the shared in-memory exporter; clear before and after each test."""
    _EXPORTER.clear()
    yield _EXPORTER
    _EXPORTER.clear()


# ---------------- Decorator behavior ----------------


@pytest.mark.asyncio
async def test_traced_agent_opens_and_closes_span(in_memory_exporter):
    @traced_agent("agent.run")
    async def fake_run(self):
        add_span_attributes({"ark.run_id": "abc"})
        add_span_input({"user_input": "hi"})
        add_span_output({"content": "hello"})
        return "done"

    result = await fake_run(self=None)
    assert result == "done"

    spans = in_memory_exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.name == "agent.run"
    assert span.attributes["openinference.span.kind"] == "AGENT"
    assert span.attributes["ark.run_id"] == "abc"
    assert "input.value" in span.attributes
    assert "output.value" in span.attributes


@pytest.mark.asyncio
async def test_traced_chain_records_exception(in_memory_exporter):
    @traced_chain("agent.model_phase")
    async def fail_phase(self):
        raise ValueError("boom")

    with pytest.raises(ValueError):
        await fail_phase(self=None)

    spans = in_memory_exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.name == "agent.model_phase"
    assert span.status.status_code.name == "ERROR"
    assert span.attributes["ark.error_type"] == "ValueError"
    assert any(ev.name == "exception" for ev in span.events)


@pytest.mark.asyncio
async def test_traced_tool_marks_error_result_as_failed(in_memory_exporter):
    class _ErrorResult:
        is_error = True
        tool_call_id = "call_1"
        result_type = "error"
        content = "oops"
        loop_action = None

    class _Tool:
        @traced_tool
        async def _execute_single(self, tc, ctx, handler):
            return _ErrorResult()

    class _ToolCall:
        id = "call_1"
        name = "search"
        arguments = {"q": "x"}

    await _Tool()._execute_single(_ToolCall(), {}, None)

    spans = in_memory_exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.name == "tool.search"
    assert span.attributes["openinference.span.kind"] == "TOOL"
    assert span.attributes["tool.name"] == "search"
    assert span.attributes["ark.is_error"] is True
    assert span.status.status_code.name == "ERROR"


@pytest.mark.asyncio
async def test_traced_tool_records_exception(in_memory_exporter):
    class _Tool:
        @traced_tool
        async def _execute_single(self, tc, ctx, handler):
            raise RuntimeError("tool exploded")

    class _ToolCall:
        id = "call_2"
        name = "calc"
        arguments = {}

    with pytest.raises(RuntimeError):
        await _Tool()._execute_single(_ToolCall(), {}, None)

    spans = in_memory_exporter.get_finished_spans()
    assert spans[0].status.status_code.name == "ERROR"
    assert spans[0].attributes["ark.error_type"] == "RuntimeError"


@pytest.mark.asyncio
async def test_nested_decorators_form_parent_child_tree(in_memory_exporter):
    @traced_chain("agent.tool_phase")
    async def inner():
        add_span_attributes({"ark.turn": 1})

    @traced_chain("agent.turn")
    async def middle():
        await inner()

    @traced_agent("agent.run")
    async def outer(self):
        await middle()

    await outer(self=None)

    spans = in_memory_exporter.get_finished_spans()
    by_name = {s.name: s for s in spans}
    assert set(by_name) == {"agent.run", "agent.turn", "agent.tool_phase"}

    run_span = by_name["agent.run"]
    turn_span = by_name["agent.turn"]
    tool_span = by_name["agent.tool_phase"]

    assert run_span.parent is None
    assert turn_span.parent is not None and turn_span.parent.span_id == run_span.context.span_id
    assert tool_span.parent is not None and tool_span.parent.span_id == turn_span.context.span_id


def test_helpers_are_safe_with_noop_tracer():
    """When no provider is configured, the global NoOp span swallows writes."""
    add_span_attributes({"any": "thing"})
    add_span_input({"foo": 1})
    add_span_output({"bar": 2})


# ---------------- Provider resolution ----------------


def test_no_tracing_env_returns_none(monkeypatch):
    monkeypatch.delenv("TRACING", raising=False)
    assert setup_tracing_from_env(service_name="ark-agentic-test") is None


def test_unknown_provider_in_tracing_logs_warning(monkeypatch, caplog):
    monkeypatch.setenv("TRACING", "phoenix,bogus")
    monkeypatch.setenv("PHOENIX_COLLECTOR_ENDPOINT", "http://localhost:6006/v1/traces")
    with caplog.at_level("WARNING"):
        tp = setup_tracing_from_env(service_name="ark-agentic-test")
    try:
        assert tp is not None
        assert any("bogus" in r.message for r in caplog.records)
    finally:
        shutdown_tracing(tp)


def test_auto_mode_picks_credentialled_only(monkeypatch):
    """auto mode enables only providers whose has_credentials returns True."""
    # Clear all credentials.
    for var in (
        "PHOENIX_COLLECTOR_ENDPOINT",
        "LANGFUSE_PUBLIC_KEY",
        "LANGFUSE_SECRET_KEY",
        "OTEL_EXPORTER_OTLP_ENDPOINT",
    ):
        monkeypatch.delenv(var, raising=False)

    # Only Langfuse credentials present.
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk_test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk_test")
    monkeypatch.setenv("TRACING", "auto")

    enabled = [
        name for name, cls in PROVIDERS.items() if cls().has_credentials()
    ]
    assert enabled == ["langfuse"]


def test_console_provider_does_not_self_enable_in_auto(monkeypatch):
    """Console must always be explicit — too noisy for auto."""
    from ark_agentic.core.observability.providers import ConsoleProvider

    assert ConsoleProvider().has_credentials() is False


def test_console_provider_installs_processor(monkeypatch):
    monkeypatch.setenv("TRACING", "console")
    tp = setup_tracing_from_env(service_name="ark-agentic-test")
    try:
        assert tp is not None
        assert getattr(tp, "_ark_providers", None) is not None
        assert [p.name for p in tp._ark_providers] == ["console"]
    finally:
        shutdown_tracing(tp)
