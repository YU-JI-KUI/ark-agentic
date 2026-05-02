"""Observability — OTel decorators + multi-backend provider registry."""

from .decorators import (
    add_span_attributes,
    add_span_input,
    add_span_output,
    traced_agent,
    traced_chain,
    traced_tool,
)
from .links import current_trace_id_or_none, resolve_trace_link_template
from .tracing import (
    get_tracer,
    setup_tracing_from_env,
    shutdown_tracing,
)

__all__ = [
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
