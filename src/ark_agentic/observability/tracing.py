"""Provider-neutral tracing callbacks for runner lifecycle events."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from ..core.callbacks import CallbackContext, RunnerCallbacks
from ..core.llm.errors import LLMError

try:
    from openinference.semconv.trace import OpenInferenceSpanKindValues, SpanAttributes
except ImportError:  # pragma: no cover - best-effort fallback when optional deps missing
    class _SpanAttributes:
        OPENINFERENCE_SPAN_KIND = "openinference.span.kind"
        INPUT_VALUE = "input.value"
        INPUT_MIME_TYPE = "input.mime_type"
        OUTPUT_VALUE = "output.value"
        OUTPUT_MIME_TYPE = "output.mime_type"
        SESSION_ID = "session.id"
        USER_ID = "user.id"
        AGENT_NAME = "agent.name"
        TOOL_NAME = "tool.name"
        TOOL_PARAMETERS = "tool.parameters"

    class _OpenInferenceSpanKindValues:
        AGENT = "AGENT"
        CHAIN = "CHAIN"
        TOOL = "TOOL"

    SpanAttributes = _SpanAttributes()  # type: ignore[assignment]
    OpenInferenceSpanKindValues = _OpenInferenceSpanKindValues()  # type: ignore[assignment]

try:
    from opentelemetry.trace import Status, StatusCode
except ImportError:  # pragma: no cover - best-effort fallback when optional deps missing
    Status = None

    class _StatusCode:
        OK = "OK"
        ERROR = "ERROR"

    StatusCode = _StatusCode()  # type: ignore[assignment]


_JSON_MIME_TYPE = "application/json"
_SPAN_STORE_KEY = "_observability_spans"


def get_tracer(name: str) -> Any | None:
    try:
        from opentelemetry import trace
    except ImportError:
        return None
    return trace.get_tracer(name)


def _set_span_attributes(span: Any, attributes: dict[str, Any] | None) -> None:
    if not attributes:
        return
    for key, value in attributes.items():
        if value is None:
            continue
        if isinstance(value, (str, bool, int, float)):
            span.set_attribute(key, value)
        else:
            span.set_attribute(key, str(value))


def _to_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _json_input_output_attributes(
    *,
    input_value: Any | None = None,
    output_value: Any | None = None,
) -> dict[str, Any]:
    attrs: dict[str, Any] = {}
    if input_value is not None:
        attrs[SpanAttributes.INPUT_VALUE] = _to_json(input_value)
        attrs[SpanAttributes.INPUT_MIME_TYPE] = _JSON_MIME_TYPE
    if output_value is not None:
        attrs[SpanAttributes.OUTPUT_VALUE] = _to_json(output_value)
        attrs[SpanAttributes.OUTPUT_MIME_TYPE] = _JSON_MIME_TYPE
    return attrs


def _response_payload(response: Any) -> dict[str, Any]:
    return {
        "content": getattr(response, "content", None),
        "tool_calls": [
            {
                "id": tc.id,
                "name": tc.name,
                "arguments": tc.arguments,
            }
            for tc in (getattr(response, "tool_calls", None) or [])
        ],
        "metadata": getattr(response, "metadata", {}),
    }


def _tool_result_payload(results: list[Any]) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for result in results:
        payload.append(
            {
                "tool_call_id": getattr(result, "tool_call_id", None),
                "result_type": getattr(
                    getattr(result, "result_type", None),
                    "value",
                    getattr(result, "result_type", None),
                ),
                "content": getattr(result, "content", None),
                "is_error": getattr(result, "is_error", None),
                "metadata": getattr(result, "metadata", {}),
                "loop_action": getattr(
                    getattr(result, "loop_action", None),
                    "value",
                    getattr(result, "loop_action", None),
                ),
            }
        )
    return payload


def _tool_call_payload(tool_calls: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "id": tc.id,
            "name": tc.name,
            "arguments": tc.arguments,
        }
        for tc in tool_calls
    ]


@dataclass
class _ManagedSpan:
    manager: Any
    span: Any
    closed: bool = False

    def set_attributes(self, attributes: dict[str, Any] | None) -> None:
        _set_span_attributes(self.span, attributes)

    def set_status(self, status_code: Any, description: str | None = None) -> None:
        setter = getattr(self.span, "set_status", None)
        if not callable(setter):
            return
        if Status is not None:
            setter(Status(status_code, description))
            return
        setter(status_code)

    def close(self, exc: BaseException | None = None) -> None:
        if self.closed:
            return
        self.closed = True
        if exc is not None:
            self.set_status(StatusCode.ERROR, str(exc))
            self.span.set_attribute("error", True)
            self.span.set_attribute("ark.error_type", type(exc).__name__)
            self.span.set_attribute("ark.error_message", str(exc))
            if isinstance(exc, LLMError):
                self.span.set_attribute("ark.error_reason", exc.reason.value)
                if exc.model:
                    self.span.set_attribute("ark.error_model", exc.model)
            record_exception = getattr(self.span, "record_exception", None)
            if callable(record_exception):
                record_exception(exc)
        self.manager.__exit__(
            type(exc) if exc else None,
            exc,
            exc.__traceback__ if exc else None,
        )


def _start_managed_span(
    name: str,
    *,
    tracer_name: str,
    attributes: dict[str, Any] | None = None,
) -> _ManagedSpan | None:
    tracer = get_tracer(tracer_name)
    if tracer is None:
        return None
    manager = tracer.start_as_current_span(name)
    span = manager.__enter__()
    handle = _ManagedSpan(manager=manager, span=span)
    handle.set_attributes(attributes)
    return handle


def _get_span_store(ctx: CallbackContext) -> dict[str, _ManagedSpan]:
    return ctx.runtime.setdefault(_SPAN_STORE_KEY, {})


def _close_span(
    ctx: CallbackContext,
    key: str,
    *,
    attributes: dict[str, Any] | None = None,
    status_code: Any | None = None,
    status_description: str | None = None,
    exc: BaseException | None = None,
) -> None:
    span = _get_span_store(ctx).pop(key, None)
    if span is None:
        return
    span.set_attributes(attributes)
    if exc is None and status_code is not None:
        span.set_status(status_code, status_description)
    span.close(exc)


def create_tracing_callbacks(
    *,
    agent_id: str | None = None,
    agent_name: str | None = None,
    tracer_name: str = "ark_agentic.runner",
) -> RunnerCallbacks:
    """Create tracing hooks for the runner lifecycle."""

    async def _before_agent(ctx: CallbackContext) -> None:
        run_meta = ctx.runtime.get("run", {})
        span_name = run_meta.get("agent_id") or agent_id or "agent.run"
        handle = _start_managed_span(
            span_name,
            tracer_name=tracer_name,
            attributes={
                SpanAttributes.OPENINFERENCE_SPAN_KIND: getattr(
                    OpenInferenceSpanKindValues.AGENT,
                    "value",
                    OpenInferenceSpanKindValues.AGENT,
                ),
                SpanAttributes.SESSION_ID: ctx.session.session_id,
                SpanAttributes.USER_ID: run_meta.get("user_id") or ctx.session.user_id,
                SpanAttributes.AGENT_NAME: run_meta.get("agent_name") or agent_name,
                "ark.agent_id": run_meta.get("agent_id") or agent_id,
                "ark.session_id": ctx.session.session_id,
                "ark.user_id": run_meta.get("user_id") or ctx.session.user_id,
                "ark.stream": run_meta.get("stream"),
                "ark.model": run_meta.get("model"),
                "ark.skill_load_mode": run_meta.get("skill_load_mode"),
                "ark.trace_id": ctx.input_context.get("temp:trace_id"),
                "ark.agent_name": run_meta.get("agent_name") or agent_name,
                **_json_input_output_attributes(
                    input_value={
                        "user_input": ctx.user_input,
                        "input_context": ctx.input_context,
                    }
                ),
            },
        )
        if handle is not None:
            _get_span_store(ctx)["agent"] = handle
        return None

    async def _after_agent(ctx: CallbackContext, *, response: Any) -> None:
        model_error = ctx.runtime.pop("model_error", None)
        if isinstance(model_error, BaseException):
            _close_span(ctx, "model", exc=model_error)
        _close_span(ctx, "tool")
        span_store = _get_span_store(ctx)
        for key in [k for k in list(span_store) if k.startswith("tool_call:")]:
            _close_span(ctx, key)

        run_result = ctx.runtime.get("run_result")
        _close_span(
            ctx,
            "agent",
            attributes={
                "ark.response_role": getattr(response, "role", None),
                "ark.response_has_tool_calls": bool(
                    getattr(response, "tool_calls", None)
                ),
                "ark.response_content_length": len(
                    getattr(response, "content", "") or ""
                ),
                "ark.turns": getattr(run_result, "turns", None),
                "ark.tool_calls_count": getattr(run_result, "tool_calls_count", None),
                "ark.prompt_tokens": getattr(run_result, "prompt_tokens", None),
                "ark.completion_tokens": getattr(run_result, "completion_tokens", None),
                "ark.stopped_by_limit": getattr(run_result, "stopped_by_limit", None),
                **_json_input_output_attributes(
                    output_value=_response_payload(response)
                ),
            },
            status_code=StatusCode.OK,
        )
        ctx.runtime.pop(_SPAN_STORE_KEY, None)
        return None

    async def _before_model(
        ctx: CallbackContext,
        *,
        turn: int,
        messages: list[dict[str, Any]],
    ) -> None:
        phase_meta = ctx.runtime.get("model_phase", {})
        handle = _start_managed_span(
            "agent.model_phase",
            tracer_name=tracer_name,
            attributes={
                SpanAttributes.OPENINFERENCE_SPAN_KIND: getattr(
                    OpenInferenceSpanKindValues.CHAIN,
                    "value",
                    OpenInferenceSpanKindValues.CHAIN,
                ),
                "ark.turn": turn,
                "ark.streaming": phase_meta.get("streaming"),
                "ark.message_count": len(messages),
                "ark.tool_schema_count": phase_meta.get("tool_schema_count"),
                "ark.model_override": phase_meta.get("model_override"),
                **_json_input_output_attributes(input_value={"messages": messages}),
            },
        )
        if handle is not None:
            _get_span_store(ctx)["model"] = handle
        return None

    async def _after_model(ctx: CallbackContext, *, turn: int, response: Any) -> None:
        ctx.runtime.pop("model_error", None)
        usage = (
            response.metadata.get("usage", {})
            if getattr(response, "metadata", None)
            else {}
        )
        _close_span(
            ctx,
            "model",
            attributes={
                "ark.turn": turn,
                "ark.finish_reason": (
                    response.metadata.get("finish_reason")
                    if response.metadata
                    else None
                ),
                "ark.response_content_length": len(response.content or ""),
                "ark.tool_call_count": len(response.tool_calls or []),
                "ark.prompt_tokens": usage.get("prompt_tokens"),
                "ark.completion_tokens": usage.get("completion_tokens"),
                **_json_input_output_attributes(
                    output_value=_response_payload(response)
                ),
            },
        )
        return None

    async def _before_tool(
        ctx: CallbackContext,
        *,
        turn: int,
        tool_calls: list[Any],
    ) -> None:
        handle = _start_managed_span(
            "agent.tool_phase",
            tracer_name=tracer_name,
            attributes={
                SpanAttributes.OPENINFERENCE_SPAN_KIND: getattr(
                    OpenInferenceSpanKindValues.CHAIN,
                    "value",
                    OpenInferenceSpanKindValues.CHAIN,
                ),
                "ark.turn": turn,
                "ark.tool_count": len(tool_calls),
                "ark.tool_names": ",".join(tc.name for tc in tool_calls),
                **_json_input_output_attributes(
                    input_value=_tool_call_payload(tool_calls)
                ),
            },
        )
        if handle is not None:
            _get_span_store(ctx)["tool"] = handle
        span_store = _get_span_store(ctx)
        for tc in tool_calls:
            tool_handle = _start_managed_span(
                f"tool.{tc.name}",
                tracer_name=tracer_name,
                attributes={
                    SpanAttributes.OPENINFERENCE_SPAN_KIND: getattr(
                        OpenInferenceSpanKindValues.TOOL,
                        "value",
                        OpenInferenceSpanKindValues.TOOL,
                    ),
                    "ark.turn": turn,
                    "ark.tool_call_id": tc.id,
                    SpanAttributes.TOOL_NAME: tc.name,
                    SpanAttributes.TOOL_PARAMETERS: _to_json(tc.arguments),
                    **_json_input_output_attributes(
                        input_value={
                            "id": tc.id,
                            "name": tc.name,
                            "arguments": tc.arguments,
                        }
                    ),
                },
            )
            if tool_handle is not None:
                span_store[f"tool_call:{tc.id}"] = tool_handle
        return None

    async def _after_tool(ctx: CallbackContext, *, turn: int, results: list[Any]) -> None:
        result_by_tool_call_id = {
            getattr(result, "tool_call_id", None): result
            for result in results
            if getattr(result, "tool_call_id", None) is not None
        }
        span_store = _get_span_store(ctx)
        for key in [k for k in list(span_store) if k.startswith("tool_call:")]:
            tool_call_id = key.split(":", 1)[1]
            result = result_by_tool_call_id.get(tool_call_id)
            _close_span(
                ctx,
                key,
                attributes=(
                    {
                        "ark.turn": turn,
                        "ark.is_error": getattr(result, "is_error", None),
                        "ark.result_type": getattr(
                            getattr(result, "result_type", None),
                            "value",
                            getattr(result, "result_type", None),
                        ),
                        "ark.loop_action": getattr(
                            getattr(result, "loop_action", None),
                            "value",
                            getattr(result, "loop_action", None),
                        ),
                        **_json_input_output_attributes(
                            output_value=(
                                _tool_result_payload([result])[0]
                                if result is not None
                                else None
                            )
                        ),
                    }
                    if result is not None
                    else {"ark.turn": turn}
                ),
            )
        _close_span(
            ctx,
            "tool",
            attributes={
                "ark.turn": turn,
                "ark.result_count": len(results),
                "ark.error_count": sum(
                    1 for result in results if getattr(result, "is_error", False)
                ),
                "ark.stop_result_count": sum(
                    1
                    for result in results
                    if getattr(getattr(result, "loop_action", None), "value", None)
                    == "stop"
                ),
                **_json_input_output_attributes(
                    output_value=_tool_result_payload(results)
                ),
            },
        )
        return None

    return RunnerCallbacks(
        before_agent=[_before_agent],
        after_agent=[_after_agent],
        before_model=[_before_model],
        after_model=[_after_model],
        before_tool=[_before_tool],
        after_tool=[_after_tool],
    )


@contextmanager
def start_span(
    name: str,
    *,
    attributes: dict[str, Any] | None = None,
    tracer_name: str = "ark_agentic",
) -> Iterator[Any | None]:
    """Start a best-effort span and no-op when OTel is unavailable."""
    tracer = get_tracer(tracer_name)
    if tracer is None:
        yield None
        return

    with tracer.start_as_current_span(name) as span:
        _set_span_attributes(span, attributes)
        yield span
