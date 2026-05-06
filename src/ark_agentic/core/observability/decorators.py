"""Runner-boundary OTel span decorators.

Three decorators wrap the runner's phase methods so that each phase becomes
an OTel span with the appropriate OpenInference kind. Three helpers let the
function body write dynamic attributes / input / output to the active span.

Design rules
------------
- Static fields (kind, span name) → decorator parameter.
- Dynamic fields (session_id, user_input, runtime response) → call
  add_span_attributes / add_span_input / add_span_output inside the body.
- All decorators rely on ``with start_as_current_span(...) as span`` so that
  exception paths close the span via ``__exit__`` — no manual lifecycle.
- When no TracerProvider is configured the global NoOp tracer makes every
  operation zero-cost.
"""

from __future__ import annotations

import json
import logging
import inspect
from functools import wraps
from typing import Any, Awaitable, Callable, TypeVar

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

logger = logging.getLogger(__name__)

try:
    from openinference.semconv.trace import (
        OpenInferenceSpanKindValues,
        SpanAttributes,
    )

    _SPAN_KIND_AGENT = OpenInferenceSpanKindValues.AGENT.value
    _SPAN_KIND_CHAIN = OpenInferenceSpanKindValues.CHAIN.value
    _SPAN_KIND_TOOL = OpenInferenceSpanKindValues.TOOL.value
    _ATTR_SPAN_KIND = SpanAttributes.OPENINFERENCE_SPAN_KIND
    _ATTR_INPUT_VALUE = SpanAttributes.INPUT_VALUE
    _ATTR_INPUT_MIME = SpanAttributes.INPUT_MIME_TYPE
    _ATTR_OUTPUT_VALUE = SpanAttributes.OUTPUT_VALUE
    _ATTR_OUTPUT_MIME = SpanAttributes.OUTPUT_MIME_TYPE
    _ATTR_TOOL_NAME = SpanAttributes.TOOL_NAME
    _ATTR_TOOL_PARAMETERS = SpanAttributes.TOOL_PARAMETERS
except ImportError:  # pragma: no cover — fallback if semconv missing
    _SPAN_KIND_AGENT = "AGENT"
    _SPAN_KIND_CHAIN = "CHAIN"
    _SPAN_KIND_TOOL = "TOOL"
    _ATTR_SPAN_KIND = "openinference.span.kind"
    _ATTR_INPUT_VALUE = "input.value"
    _ATTR_INPUT_MIME = "input.mime_type"
    _ATTR_OUTPUT_VALUE = "output.value"
    _ATTR_OUTPUT_MIME = "output.mime_type"
    _ATTR_TOOL_NAME = "tool.name"
    _ATTR_TOOL_PARAMETERS = "tool.parameters"


_TRACER_NAME = "ark_agentic.runner"
_JSON_MIME = "application/json"

F = TypeVar("F", bound=Callable[..., Awaitable[Any]])


def _to_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _coerce_attr(value: Any) -> Any:
    if isinstance(value, (str, bool, int, float)):
        return value
    return str(value)


# ---------- Internal factory ----------


def _traced(span_name: str, kind: str, *, span_name_template: str = None) -> Callable[[F], F]:
    def deco(fn: F) -> F:
        @wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            tracer = trace.get_tracer(_TRACER_NAME)
            current_span_name = span_name
            if span_name_template:
                sig = inspect.signature(fn)
                bound = sig.bind(*args, **kwargs)
                bound.apply_defaults()
                current_span_name = span_name_template.format(**bound.arguments)

            with tracer.start_as_current_span(current_span_name) as span:
                span.set_attribute(_ATTR_SPAN_KIND, kind)
                try:
                    return await fn(*args, **kwargs)
                except BaseException as exc:
                    span.set_status(Status(StatusCode.ERROR, str(exc)))
                    span.record_exception(exc)
                    span.set_attribute("ark.error_type", type(exc).__name__)
                    raise

        return wrapper  # type: ignore[return-value]

    return deco


# ---------- Public decorators ----------


def traced_agent(span_name: str = "agent.run", span_name_template: str = None) -> Callable[[F], F]:
    """Wrap BaseAgent.run — opens an OpenInference AGENT span."""
    return _traced(span_name, _SPAN_KIND_AGENT, span_name_template=span_name_template)


def traced_chain(span_name: str, span_name_template: str = None) -> Callable[[F], F]:
    """Wrap a runner phase — opens an OpenInference CHAIN span."""
    return _traced(span_name, _SPAN_KIND_CHAIN, span_name_template=span_name_template)


def traced_tool(fn: F) -> F:
    """Wrap ToolExecutor._execute_single — span name from ToolCall.name.

    The wrapped function must accept ``(self, tool_call, ...)`` so the
    decorator can read ``tool_call.name`` for the span name.
    """

    @wraps(fn)
    async def wrapper(self: Any, tc: Any, *args: Any, **kwargs: Any) -> Any:
        tracer = trace.get_tracer(_TRACER_NAME)
        with tracer.start_as_current_span(f"tool.{tc.name}") as span:
            span.set_attribute(_ATTR_SPAN_KIND, _SPAN_KIND_TOOL)
            span.set_attribute(_ATTR_TOOL_NAME, tc.name)
            span.set_attribute("ark.tool_call_id", tc.id)
            span.set_attribute(_ATTR_TOOL_PARAMETERS, _to_json(tc.arguments))
            add_span_input({"id": tc.id, "name": tc.name, "arguments": tc.arguments})
            try:
                result = await fn(self, tc, *args, **kwargs)
            except BaseException as exc:
                span.set_status(Status(StatusCode.ERROR, str(exc)))
                span.record_exception(exc)
                span.set_attribute("ark.error_type", type(exc).__name__)
                raise
            if getattr(result, "is_error", False):
                span.set_status(Status(StatusCode.ERROR, "tool returned error_result"))
                span.set_attribute("ark.is_error", True)
            try:
                add_span_output(_tool_result_payload(result))
            except Exception as e:  # pragma: no cover — never let telemetry break the call
                logger.debug("traced_tool: failed to serialize output: %s", e)
            return result

    return wrapper  # type: ignore[return-value]


# ---------- Active-span helpers ----------


def add_span_attributes(attrs: dict[str, Any]) -> None:
    """Write attributes on the currently active span. NoOp safe."""
    span = trace.get_current_span()
    for key, value in attrs.items():
        if value is None:
            continue
        span.set_attribute(key, _coerce_attr(value))


def add_span_input(value: Any) -> None:
    """Write input.value (JSON) on the currently active span."""
    span = trace.get_current_span()
    span.set_attribute(_ATTR_INPUT_VALUE, _to_json(value))
    span.set_attribute(_ATTR_INPUT_MIME, _JSON_MIME)


def add_span_output(value: Any) -> None:
    """Write output.value (JSON) on the currently active span."""
    span = trace.get_current_span()
    span.set_attribute(_ATTR_OUTPUT_VALUE, _to_json(value))
    span.set_attribute(_ATTR_OUTPUT_MIME, _JSON_MIME)


# ---------- Internal payload helpers ----------


def _tool_result_payload(result: Any) -> dict[str, Any]:
    return {
        "tool_call_id": getattr(result, "tool_call_id", None),
        "result_type": getattr(
            getattr(result, "result_type", None), "value",
            getattr(result, "result_type", None),
        ),
        "is_error": getattr(result, "is_error", None),
        "content": getattr(result, "content", None),
        "loop_action": getattr(
            getattr(result, "loop_action", None), "value",
            getattr(result, "loop_action", None),
        ),
    }
