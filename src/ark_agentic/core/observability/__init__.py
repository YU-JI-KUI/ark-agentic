"""Observability — OTel decorators + multi-backend provider registry."""

from .decorators import (
    add_span_attributes,
    add_span_input,
    add_span_output,
    traced_agent,
    traced_chain,
    traced_tool,
)
from .tracing import (
    get_tracer,
    setup_tracing_from_env,
    shutdown_tracing,
)

__all__ = [
    "add_span_attributes",
    "add_span_input",
    "add_span_output",
    "get_tracer",
    "setup_tracing_from_env",
    "shutdown_tracing",
    "traced_agent",
    "traced_chain",
    "traced_tool",
]
