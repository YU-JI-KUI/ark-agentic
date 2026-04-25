# Runner Telemetry Redesign — Decorator + Multi-Provider OTel

**Date:** 2026-04-25
**Branch:** `harness_engineering_2.0`
**Status:** Approved (pending spec review)

## 1. Background & Goals

The current `RunnerCallbacks` system mixes business logic (guard/retry/state mutation) with observability (Phoenix span management) into the same hook surface. As a result:

- `CallbackContext.metadata` is a god dict (system data + private span store + user data, separated only by `_` prefix).
- Hook kwargs (`streaming`, `model`, `tool_count`, …) are an implicit contract; new fields require touching both runner and every callback site.
- ABORT / exception / cancellation paths do not guarantee `after_*` hooks fire, leaking tracing spans and skipping `temp_state` cleanup.
- Adding a new monitoring backend (Langfuse, LangSmith, generic OTLP) requires hand-writing OpenInference attribute mapping in our own `tracing.py`.

**Goal:** Redesign so that:

1. Runner emits OTel spans at well-defined boundaries via decorators — no manual span store, no hook bookkeeping.
2. Business callbacks (`RunnerCallbacks`) stay untouched, decoupled from observability entirely.
3. Switching or combining monitoring backends (Phoenix / Langfuse / Console / generic OTLP) is a single env-variable change with zero code touch.
4. LangChain `ChatOpenAI` LLM internals (streaming first-token latency, invocation parameters, token usage) are captured automatically via `openinference-instrumentation-langchain`, not hand-rolled.
5. Exception / abort / cancellation paths close spans correctly via Python context-manager guarantees (incidentally fixes B1 / B2 from prior code review).

## 2. Architecture

Three layers, sharply separated:

```
Layer 1 — Business callbacks (UNCHANGED)
  RunnerCallbacks (8 hooks) + HookAction enum
  Concerns: guard / retry / state mutation / UI event dispatch
  Has zero observability code.

Layer 2 — Decorators (NEW, ~80 LOC)
  @traced_agent / @traced_chain / @traced_tool
  add_span_attributes() / add_span_input() / add_span_output()
  Concerns: open OTel span at runner phase boundaries, write ark.* attributes

Layer 3 — Provider registry (REFACTORED, ~150 LOC)
  PROVIDERS dict + TracingProvider Protocol
  PhoenixProvider / LangfuseProvider / ConsoleProvider / OTLPProvider
  Concerns: route OTel spans to one or more monitoring backends

External:
  openinference-instrumentation-langchain
  → Auto-captures ChatOpenAI.ainvoke as a child span of whatever
    ark span is currently active (streaming token, params, usage all free)
```

### 2.1 Resulting trace tree (Phoenix / Langfuse UI)

```
[agent.run]                          ← @traced_agent (AGENT)
├─ [agent.turn:1]                    ← @traced_chain (CHAIN)
│   ├─ [agent.model_phase:1]         ← @traced_chain
│   │   └─ [ChatOpenAI]              ← openinference auto (LLM)
│   │       └─ [openai.chat]         ← openinference auto
│   └─ [agent.tool_phase:1]          ← @traced_chain
│       ├─ [tool:search_news]        ← @traced_tool (TOOL)
│       └─ [tool:get_quote]          ← @traced_tool
└─ [agent.turn:2]
    └─ [agent.model_phase:2]
        └─ [ChatOpenAI]
```

## 3. Decorator API

**File:** `src/ark_agentic/core/observability/decorators.py` (new, ~80 LOC).

Three decorators + three helpers:

| Symbol | Purpose | Signature |
|---|---|---|
| `traced_agent(name)` | Wrap `AgentRunner.run` (AGENT span kind) | decorator factory |
| `traced_chain(name)` | Wrap turn / model_phase / tool_phase (CHAIN span kind) | decorator factory |
| `traced_tool` | Wrap `ToolExecutor._execute_single` (TOOL span kind, name from `ToolCall.name`) | decorator (no args) |
| `add_span_attributes(dict)` | Write attributes on the active span | helper |
| `add_span_input(value)` | Write `input.value` (JSON) | helper |
| `add_span_output(value)` | Write `output.value` (JSON) | helper |

### 3.1 Design rules

- **Static fields** (e.g., `kind="AGENT"`, fixed semantic conventions) → decorator parameter.
- **Dynamic fields** (e.g., `session_id`, `user_input`, runtime `response`) → call `add_span_*()` inside the function body.
- **Never** push the decorator into a "reflect-args-to-attributes" mapping engine — that recreates the god-dict problem.
- All three decorators wrap `with tracer.start_as_current_span(...) as span:` so:
  - Exception paths close the span via `__exit__` (fixes B1).
  - Tool errors are detected via return-value inspection (`result.is_error`) and the span gets `set_status(ERROR)` + `record_exception` (fixes B2).
  - `CancelledError` / `KeyboardInterrupt` propagate through context manager — span still closes.

### 3.2 Reference implementation

```python
# src/ark_agentic/core/observability/decorators.py
from functools import wraps
from typing import Any, Callable
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

try:
    from openinference.semconv.trace import SpanAttributes, OpenInferenceSpanKindValues
except ImportError:
    # fallback constants (preserve existing tracing.py fallback semantics)
    ...

_TRACER_NAME = "ark_agentic.runner"


def _traced(span_name: str, kind: str) -> Callable:
    def deco(fn: Callable) -> Callable:
        @wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            tracer = trace.get_tracer(_TRACER_NAME)
            with tracer.start_as_current_span(span_name) as span:
                span.set_attribute(SpanAttributes.OPENINFERENCE_SPAN_KIND, kind)
                try:
                    return await fn(*args, **kwargs)
                except BaseException as exc:
                    span.set_status(Status(StatusCode.ERROR, str(exc)))
                    span.record_exception(exc)
                    span.set_attribute("ark.error_type", type(exc).__name__)
                    raise
        return wrapper
    return deco


def traced_agent(span_name: str = "agent.run") -> Callable:
    return _traced(span_name, OpenInferenceSpanKindValues.AGENT.value)


def traced_chain(span_name: str) -> Callable:
    return _traced(span_name, OpenInferenceSpanKindValues.CHAIN.value)


def traced_tool(fn: Callable) -> Callable:
    """For ToolExecutor._execute_single. Span name from ToolCall.name."""
    @wraps(fn)
    async def wrapper(self, tc, *args, **kwargs):
        tracer = trace.get_tracer(_TRACER_NAME)
        with tracer.start_as_current_span(f"tool.{tc.name}") as span:
            span.set_attribute(
                SpanAttributes.OPENINFERENCE_SPAN_KIND,
                OpenInferenceSpanKindValues.TOOL.value,
            )
            span.set_attribute(SpanAttributes.TOOL_NAME, tc.name)
            span.set_attribute("ark.tool_call_id", tc.id)
            span.set_attribute(SpanAttributes.TOOL_PARAMETERS, _to_json(tc.arguments))
            add_span_input({"id": tc.id, "name": tc.name, "arguments": tc.arguments})
            try:
                result = await fn(self, tc, *args, **kwargs)
                if getattr(result, "is_error", False):
                    span.set_status(Status(StatusCode.ERROR, "tool returned error"))
                    span.set_attribute("ark.is_error", True)
                add_span_output(_tool_result_payload(result))
                return result
            except BaseException as exc:
                span.set_status(Status(StatusCode.ERROR, str(exc)))
                span.record_exception(exc)
                raise
    return wrapper


def add_span_attributes(attrs: dict[str, Any]) -> None:
    span = trace.get_current_span()
    for k, v in attrs.items():
        if v is None:
            continue
        if isinstance(v, (str, bool, int, float)):
            span.set_attribute(k, v)
        else:
            span.set_attribute(k, str(v))


def add_span_input(value: Any) -> None:
    span = trace.get_current_span()
    span.set_attribute(SpanAttributes.INPUT_VALUE, _to_json(value))
    span.set_attribute(SpanAttributes.INPUT_MIME_TYPE, "application/json")


def add_span_output(value: Any) -> None:
    span = trace.get_current_span()
    span.set_attribute(SpanAttributes.OUTPUT_VALUE, _to_json(value))
    span.set_attribute(SpanAttributes.OUTPUT_MIME_TYPE, "application/json")
```

### 3.3 Decorator placement

| Site | Decorator |
|---|---|
| `AgentRunner.run` | `@traced_agent("agent.run")` |
| `AgentRunner._run_loop` (extract single-turn helper `_run_turn`) | `@traced_chain("agent.turn")` |
| `AgentRunner._model_phase` | `@traced_chain("agent.model_phase")` |
| `AgentRunner._tool_phase` | `@traced_chain("agent.tool_phase")` |
| `ToolExecutor._execute_single` | `@traced_tool` |

The `_run_turn` extraction is a small refactor — pull the body of the `for` loop in `_run_loop` into `async def _run_turn(self, ...)`. Keeps each turn as one chain span.

### 3.4 Runner integration example

```python
@traced_agent("agent.run")
async def run(self, session_id, user_input, user_id, ...):
    add_span_attributes({
        "session.id": session_id,
        "user.id": user_id,
        "ark.run_id": run_id,
        "ark.agent_id": self.config.skill_config.agent_id,
        "ark.agent_name": self.config.prompt_config.agent_name,
        "ark.model": params.model,
        "ark.skill_load_mode": params.skill_load_mode,
        "ark.correlation_id": input_context.get("temp:trace_id"),
    })
    add_span_input({"user_input": user_input, "input_context": input_context})

    # existing runner logic UNCHANGED

    add_span_output({"response": result.response.content, "turns": result.turns})
    add_span_attributes({
        "ark.prompt_tokens": result.prompt_tokens,
        "ark.completion_tokens": result.completion_tokens,
        "ark.tool_calls_count": result.tool_calls_count,
        "ark.stopped_by_limit": result.stopped_by_limit,
    })
    return result
```

## 4. Provider Registry & Multi-Backend

### 4.1 Single env switch: `TRACING`

| Scenario | Configuration |
|---|---|
| **Disabled** | (do not set `TRACING`) |
| **Local Phoenix** | `TRACING=phoenix` |
| **Local Console (default for dev)** | `TRACING=console` |
| **Production Langfuse** | `TRACING=langfuse` + `LANGFUSE_PUBLIC_KEY=...` `LANGFUSE_SECRET_KEY=...` |
| **Dual export** | `TRACING=phoenix,langfuse` |
| **Generic OTLP** | `TRACING=otlp` + `OTEL_EXPORTER_OTLP_ENDPOINT=...` |
| **Auto** | `TRACING=auto` (enables every provider that has credentials) |

**Auto-mode rules:**
- Phoenix: requires explicit `PHOENIX_COLLECTOR_ENDPOINT` to count as "has credentials" (avoids dev-machine errors when 6006 is not running).
- Langfuse: requires both `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY`.
- OTLP: requires `OTEL_EXPORTER_OTLP_ENDPOINT`.
- Console: always returns `False` from `has_credentials` (too noisy to auto-enable; must be explicitly listed).

`openinference-instrumentation-langchain` is enabled unconditionally whenever any provider is enabled (no separate flag — under NoOp tracer it is zero-cost, and an explicit kill switch is not worth the API surface).

### 4.2 Provider Protocol

```python
# src/ark_agentic/core/observability/providers/__init__.py
from typing import Protocol, Callable

class TracingProvider(Protocol):
    name: str
    def has_credentials(self) -> bool: ...
    def install(self, tp: "TracerProvider") -> None: ...
    def shutdown(self) -> None: ...

from .phoenix import PhoenixProvider
from .langfuse import LangfuseProvider
from .console import ConsoleProvider
from .otlp import OTLPProvider

PROVIDERS: dict[str, Callable[[], TracingProvider]] = {
    "phoenix": PhoenixProvider,
    "langfuse": LangfuseProvider,
    "console": ConsoleProvider,
    "otlp": OTLPProvider,
}
```

### 4.3 Provider implementations (one file per provider, ~30 LOC each)

```python
# providers/phoenix.py
import os
from opentelemetry.sdk.trace.export import BatchSpanProcessor

class PhoenixProvider:
    name = "phoenix"
    def __init__(self):
        self._processor = None
    def has_credentials(self) -> bool:
        return bool(os.getenv("PHOENIX_COLLECTOR_ENDPOINT"))
    def install(self, tp):
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        endpoint = os.getenv("PHOENIX_COLLECTOR_ENDPOINT", "http://127.0.0.1:6006/v1/traces")
        self._processor = BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint))
        tp.add_span_processor(self._processor)
    def shutdown(self):
        if self._processor:
            self._processor.shutdown()
```

```python
# providers/langfuse.py
import base64, os
from opentelemetry.sdk.trace.export import BatchSpanProcessor

class LangfuseProvider:
    name = "langfuse"
    def __init__(self):
        self._processor = None
    def has_credentials(self) -> bool:
        return bool(os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY"))
    def install(self, tp):
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        host = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com").rstrip("/")
        endpoint = f"{host}/api/public/otel/v1/traces"
        auth = base64.b64encode(
            f"{os.getenv('LANGFUSE_PUBLIC_KEY')}:{os.getenv('LANGFUSE_SECRET_KEY')}".encode()
        ).decode()
        self._processor = BatchSpanProcessor(
            OTLPSpanExporter(endpoint=endpoint, headers={"Authorization": f"Basic {auth}"})
        )
        tp.add_span_processor(self._processor)
    def shutdown(self):
        if self._processor:
            self._processor.shutdown()
```

```python
# providers/console.py
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, ConsoleSpanExporter

class ConsoleProvider:
    name = "console"
    def __init__(self):
        self._processor = None
    def has_credentials(self) -> bool:
        return False  # Must be explicit; auto mode never picks console.
    def install(self, tp):
        self._processor = SimpleSpanProcessor(ConsoleSpanExporter())
        tp.add_span_processor(self._processor)
    def shutdown(self):
        if self._processor:
            self._processor.shutdown()
```

```python
# providers/otlp.py
import os
from opentelemetry.sdk.trace.export import BatchSpanProcessor

class OTLPProvider:
    name = "otlp"
    def __init__(self):
        self._processor = None
    def has_credentials(self) -> bool:
        return bool(os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"))
    def install(self, tp):
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        self._processor = BatchSpanProcessor(OTLPSpanExporter())  # picks up OTEL_* env automatically
        tp.add_span_processor(self._processor)
    def shutdown(self):
        if self._processor:
            self._processor.shutdown()
```

### 4.4 Setup entry point

```python
# src/ark_agentic/core/observability/tracing.py
import os, logging
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from .providers import PROVIDERS

logger = logging.getLogger(__name__)


def _resolve_enabled_providers() -> list[str]:
    spec = os.getenv("TRACING", "").strip().lower()
    if not spec:
        return []
    if spec == "auto":
        return [n for n, cls in PROVIDERS.items() if cls().has_credentials()]
    names = [n.strip() for n in spec.split(",") if n.strip()]
    unknown = [n for n in names if n not in PROVIDERS]
    if unknown:
        logger.warning("Unknown tracing providers: %s (available: %s)", unknown, list(PROVIDERS))
    return [n for n in names if n in PROVIDERS]


def setup_tracing_from_env(service_name: str) -> TracerProvider | None:
    enabled = _resolve_enabled_providers()
    if not enabled:
        logger.info("Tracing disabled (TRACING env not set)")
        return None

    tp = TracerProvider(resource=Resource.create({"service.name": service_name}))
    instances: list = []
    for name in enabled:
        provider = PROVIDERS[name]()
        provider.install(tp)
        instances.append(provider)
        logger.info("Tracing provider enabled: %s", name)
    trace.set_tracer_provider(tp)

    try:
        from openinference.instrumentation.langchain import LangChainInstrumentor
        LangChainInstrumentor().instrument(tracer_provider=tp)
        logger.info("LangChain auto-instrumentation enabled")
    except ImportError:
        logger.warning("openinference-instrumentation-langchain not installed; LLM spans will be missing")

    tp._ark_providers = instances  # type: ignore[attr-defined]
    return tp


def shutdown_tracing(tp: TracerProvider | None) -> None:
    if tp is None:
        return
    for p in getattr(tp, "_ark_providers", []):
        try:
            p.shutdown()
        except Exception as e:
            logger.warning("Error shutting down provider %s: %s", p.name, e)
    tp.shutdown()
```

## 5. Lifecycle & Error Handling

### 5.1 Normal path
Decorator's `with start_as_current_span(...)` opens span → fn runs → `__exit__` closes span with status OK. `add_span_output` writes the response payload before return.

### 5.2 Exception path (fixes B1)
Decorator's `try / except BaseException`:
- `set_status(ERROR, str(exc))`
- `record_exception(exc)`
- `set_attribute("ark.error_type", type(exc).__name__)`
- `raise` (preserve exception for caller)

`__exit__` still runs because the `raise` propagates through context manager. Span guaranteed closed for `LLMError`, `CancelledError`, `KeyboardInterrupt`, and any other unexpected exception. No more leaked spans.

### 5.3 Tool error path (fixes B2)
`@traced_tool` inspects return value:
- If `result.is_error == True` → `set_status(ERROR, "tool returned error")` + `set_attribute("ark.is_error", True)`
- Phoenix / Langfuse will count this as a failed tool execution, matching their UI semantics.

The existing `ToolExecutor._execute_single` `try/except` continues to convert tool exceptions into `error_result` (preserves runner contract that tool failures surface to the LLM rather than crash the loop).

### 5.4 ABORT path
`_prepare_session` returns early as `RunResult` when `before_agent` callbacks return `HookAction.ABORT`. Since `run()` is wrapped by `@traced_agent`, the span closes normally with OK status. To mark the abort cause, runner adds:

```python
if r and r.action == HookAction.ABORT:
    add_span_attributes({"ark.abort_reason": "guard_rejected"})
    # ... existing ABORT path
```

## 6. File-Level Change Plan

| File | Change | Net LOC |
|---|---|---|
| `src/ark_agentic/core/observability/decorators.py` | NEW | +80 |
| `src/ark_agentic/core/observability/tracing.py` | REWRITE — strip ~500 LOC of span store / callback hook code, replace with setup/shutdown entry | -440 |
| `src/ark_agentic/core/observability/providers/__init__.py` | REWRITE — registry dict | +20 |
| `src/ark_agentic/core/observability/providers/phoenix.py` | REWRITE — single class | ~30 |
| `src/ark_agentic/core/observability/providers/langfuse.py` | REWRITE — single class | ~30 |
| `src/ark_agentic/core/observability/providers/console.py` | NEW | ~20 |
| `src/ark_agentic/core/observability/providers/otlp.py` | NEW | ~30 |
| `src/ark_agentic/core/observability/__init__.py` | EXPORT new public API (`traced_*`, `add_span_*`, `setup_tracing_from_env`, `shutdown_tracing`) | +20 |
| `src/ark_agentic/core/runner.py` | Add 4 decorators + add_span_* calls; remove `create_tracing_callbacks` import; simplify `_build_runner_callbacks` to passthrough; extract `_run_turn` helper | +30, -25 |
| `src/ark_agentic/core/tools/executor.py` | Add `@traced_tool` to `_execute_single` | +5 |
| `src/ark_agentic/app.py` | Uncomment / call `setup_tracing_from_env` in lifespan startup, `shutdown_tracing` in shutdown | +5 |
| `src/ark_agentic/agents/insurance/guard.py` | Fix `_cb` signature `**kwargs` (m2 from review) | +1 |
| `pyproject.toml` | Add `openinference-instrumentation-langchain`, `openinference-semantic-conventions`, `opentelemetry-exporter-otlp-proto-http` | +3 |
| `.env-sample` | Replace `ENABLE_PHOENIX` block with `TRACING=console` (default for local dev) + commented examples for Phoenix / Langfuse / OTLP | net same |
| `tests/unit/core/test_phoenix.py` | DELETE — superseded | -all |
| `tests/unit/core/test_tracing.py` | NEW — InMemorySpanExporter-based assertions | +150 |
| `tests/unit/core/test_callbacks.py` | Update — remove tracing-specific expectations | minor |
| `tests/unit/core/test_runner.py` | Update — remove `create_tracing_callbacks` references | minor |

**Net delta:** approximately -100 LOC, with strictly higher capability.

## 7. .env-sample Changes

The `# ---- Phoenix 可观测性 ----` block (lines 35-43 of current `.env-sample`) is replaced with:

```bash
# ---- 可观测性 (OpenTelemetry tracing) ----
# TRACING controls which monitoring backends receive spans.
# Comma-separated list of: phoenix, langfuse, console, otlp
# Special value "auto" enables every provider with valid credentials.
# Leave unset to disable tracing entirely.
TRACING=console

# Phoenix (set TRACING=phoenix to enable)
# PHOENIX_COLLECTOR_ENDPOINT=http://127.0.0.1:6006/v1/traces

# Langfuse (set TRACING=langfuse + provide credentials)
# LANGFUSE_PUBLIC_KEY=
# LANGFUSE_SECRET_KEY=
# LANGFUSE_HOST=https://cloud.langfuse.com

# Generic OTLP (set TRACING=otlp + endpoint)
# OTEL_EXPORTER_OTLP_ENDPOINT=
```

**Default for local dev:** `TRACING=console` — so contributors see span output in their terminal as a sanity check without running any external service.

## 8. Testing Strategy

OTel SDK ships `InMemorySpanExporter` — no mock framework needed.

```python
# tests/unit/core/test_tracing.py
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter


def setup_test_tracer() -> InMemorySpanExporter:
    exporter = InMemorySpanExporter()
    tp = TracerProvider()
    tp.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(tp)
    return exporter
```

**Test cases to cover:**

1. `test_agent_run_produces_trace_tree` — `run()` produces `agent.run` span with child `agent.turn`, `agent.model_phase`, `agent.tool_phase`, parent_span_id wiring correct.
2. `test_tool_error_records_exception` — tool that raises → `@traced_tool` span has status ERROR + recorded exception.
3. `test_tool_returns_error_result` — tool returns `is_error=True` → span has `ark.is_error=True` + status ERROR.
4. `test_abort_path_closes_span` — `before_agent` ABORT → `agent.run` span closes with `ark.abort_reason` set.
5. `test_llm_error_closes_model_span` — LLMError raised inside `_model_phase` → span has ERROR status + propagates through `agent.run` decorator.
6. `test_no_tracing_when_no_provider` — `setup_tracing_from_env()` returns `None` when `TRACING` unset; runner still works (NoOp tracer).
7. `test_multi_provider_fanout` — `TRACING=console,otlp` (or use a fake provider in test) → both processors receive identical spans.
8. `test_resolve_unknown_provider_warns` — `TRACING=phoenix,bogus` → warning logged, only `phoenix` enabled.
9. `test_auto_mode_picks_credentialled` — set Langfuse env, `TRACING=auto` → only Langfuse enabled (Phoenix skipped because no `PHOENIX_COLLECTOR_ENDPOINT`).
10. `test_decorator_helpers_noop_without_provider` — `add_span_attributes` on default global NoOp tracer does not raise.

## 9. Migration Steps (for the implementation plan)

1. Add deps to `pyproject.toml`, run `uv sync`.
2. Implement `decorators.py`.
3. Rewrite `providers/__init__.py` + four single-file providers.
4. Rewrite `tracing.py` to setup/shutdown entry.
5. Update `observability/__init__.py` exports.
6. Modify `runner.py`: add decorators, add helper calls, drop `create_tracing_callbacks` import, simplify `_build_runner_callbacks`, extract `_run_turn`.
7. Modify `tools/executor.py`: add `@traced_tool`.
8. Update `app.py` lifespan to call setup/shutdown.
9. Fix `guard.py` `_cb` signature.
10. Replace `.env-sample` Phoenix block.
11. Delete `tests/unit/core/test_phoenix.py`.
12. Add `tests/unit/core/test_tracing.py`.
13. Update `tests/unit/core/test_callbacks.py` and `test_runner.py` as needed.
14. Local validation: run with `TRACING=console`, exercise insurance and securities agents, eyeball span output for tree shape and attribute completeness.
15. Commit.

## 10. Local Validation Plan (post-implementation)

User explicitly requests local console verification.

```bash
# 1. Install new deps
uv sync

# 2. Set local default
export TRACING=console     # (or just rely on .env-sample default)

# 3. Start API
uv run uvicorn ark_agentic.app:app --reload --port 8080

# 4. Hit insurance and securities endpoints
curl -X POST localhost:8080/api/chat -d '{"agent": "insurance", "message": "查保单"}'
curl -X POST localhost:8080/api/chat -d '{"agent": "securities", "message": "今天行情"}'

# 5. Check stdout for ConsoleSpanExporter output. Expected:
#    - Span "agent.run" appears once per request, kind=AGENT
#    - Span "agent.turn" appears once per ReAct turn
#    - Span "agent.model_phase" wraps each LLM call
#    - Span "ChatOpenAI" appears as child of model_phase (from openinference auto-instrument)
#    - Span "agent.tool_phase" appears when tools are called
#    - Span "tool.<name>" per tool call
#    - All spans have parent_span_id matching their parent's span_id
#    - ark.* attributes (run_id, session_id, user_id, agent_id) populated
```

Confirm normal path, ABORT path (trigger via `guard.py` reject scenario), and tool error path (e.g., timeout) all produce well-formed spans.

## 11. Open Questions / Out of Scope

- **`start_span` contextmanager** in current `tracing.py` (line 484) — kept for backward compat; usage outside runner is not in scope for this redesign.
- **Cost / usage attribution** (Langfuse `usage_details.input_cost`) — relies on prompt-token counting at LLM layer, deferred to a follow-up. `openinference-instrumentation-langchain` already populates `llm.token_count.*` so basic usage shows up.
- **Streaming first-token latency** — provided automatically by `openinference-instrumentation-langchain` via `on_llm_new_token` capture, no ark code needed.
- **`before_loop_end` rename** (M3 from prior review) — out of scope for this telemetry redesign; tracked separately.
- **`HookAction` export from `core.__init__`** (m4 from prior review) — minor housekeeping, can be batched into the same PR or split.
