"""Observability — OTel decorators + multi-backend provider registry +
the framework's tracing Lifecycle component (auto-loaded by Bootstrap)."""

from .decorators import (
    add_span_attributes,
    add_span_input,
    add_span_output,
    traced_agent,
    traced_chain,
    traced_tool,
)
from .tracing_lifecycle import TracingLifecycle
from .links import current_trace_id_or_none, resolve_trace_link_template
from .tracing import (
    get_tracer,
    setup_tracing_from_env,
    shutdown_tracing,
)

__all__ = [
    "TracingLifecycle",
    "add_span_attributes",
    "add_span_input",
    "add_span_output",
    "current_trace_id_or_none",
    "get_tracer",
    "resolve_trace_link_template",
    "setup_tracing_from_env",
    "shutdown_tracing",
    "traced_agent",
    "traced_chain",
    "traced_tool",
]
