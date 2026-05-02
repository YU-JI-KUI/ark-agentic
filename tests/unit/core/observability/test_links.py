"""Unit tests for core.observability.links."""

from __future__ import annotations

import os

import pytest
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider

from ark_agentic.core.observability.links import (
    current_trace_id_or_none,
    resolve_trace_link_template,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in (
        "STUDIO_TRACE_URL_TEMPLATE",
        "TRACING",
        "PHOENIX_COLLECTOR_ENDPOINT",
        "PHOENIX_PROJECT_NAME",
        "LANGFUSE_PUBLIC_KEY",
        "LANGFUSE_HOST",
    ):
        monkeypatch.delenv(var, raising=False)
    yield


def test_returns_none_when_no_provider_configured():
    assert resolve_trace_link_template() is None


def test_explicit_template_override_wins(monkeypatch):
    monkeypatch.setenv("TRACING", "phoenix")
    monkeypatch.setenv("PHOENIX_COLLECTOR_ENDPOINT", "http://localhost:6006/v1/traces")
    monkeypatch.setenv(
        "STUDIO_TRACE_URL_TEMPLATE", "https://my-ui.example/trace/{trace_id}"
    )
    assert (
        resolve_trace_link_template()
        == "https://my-ui.example/trace/{trace_id}"
    )


def test_template_override_must_contain_placeholder(monkeypatch):
    monkeypatch.setenv("STUDIO_TRACE_URL_TEMPLATE", "https://no-placeholder.example")
    monkeypatch.setenv("TRACING", "langfuse")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
    # Override with no placeholder is invalid → fall through to provider auto-detect.
    template = resolve_trace_link_template()
    assert template is not None
    assert "{trace_id}" in template


def test_phoenix_template_constructed_from_endpoint(monkeypatch):
    monkeypatch.setenv("TRACING", "phoenix")
    monkeypatch.setenv(
        "PHOENIX_COLLECTOR_ENDPOINT", "http://phoenix.local:6006/v1/traces"
    )
    monkeypatch.setenv("PHOENIX_PROJECT_NAME", "my-project")
    assert (
        resolve_trace_link_template()
        == "http://phoenix.local:6006/projects/my-project/traces/{trace_id}"
    )


def test_phoenix_template_default_project_when_unset(monkeypatch):
    monkeypatch.setenv("PHOENIX_COLLECTOR_ENDPOINT", "http://x:6006/v1/traces")
    template = resolve_trace_link_template()
    assert template == "http://x:6006/projects/ark-agentic/traces/{trace_id}"


def test_langfuse_template_uses_default_host(monkeypatch):
    monkeypatch.setenv("TRACING", "langfuse")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    assert (
        resolve_trace_link_template()
        == "https://cloud.langfuse.com/trace/{trace_id}"
    )


def test_langfuse_template_uses_custom_host(monkeypatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
    monkeypatch.setenv("LANGFUSE_HOST", "https://my-langfuse.example/")
    assert (
        resolve_trace_link_template()
        == "https://my-langfuse.example/trace/{trace_id}"
    )


def test_current_trace_id_returns_hex_when_span_active():
    tp = TracerProvider(resource=Resource.create({"service.name": "test"}))
    trace.set_tracer_provider(tp)
    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span("test-span"):
        result = current_trace_id_or_none()
    assert result is not None
    assert len(result) == 32
    assert all(c in "0123456789abcdef" for c in result)


def test_current_trace_id_returns_none_when_no_active_span():
    # No tracer provider configured → NoOp tracer → invalid context.
    trace.set_tracer_provider(trace.NoOpTracerProvider())
    assert current_trace_id_or_none() is None
