"""Trace-UI deep-link helpers and OTel trace_id capture.

These helpers are pure (no runtime state) so the Studio config endpoint can
call them at request time without coordination with the tracer provider
lifecycle. ``current_trace_id_or_none`` is also called from the runner at
message-creation time.
"""

from __future__ import annotations

import os

from opentelemetry import trace


def current_trace_id_or_none() -> str | None:
    """Return the active span's trace_id as 32-hex, or None.

    Uses ``ctx.is_valid`` — the only correct predicate. NoOp tracer returns
    INVALID_SPAN_CONTEXT (trace_id = span_id = 0); a hex-formatted zero would
    look like a valid string but isn't, so we must check ``is_valid`` instead
    of formatting first.
    """
    ctx = trace.get_current_span().get_span_context()
    if not ctx.is_valid:
        return None
    return format(ctx.trace_id, "032x")


def resolve_trace_link_template() -> str | None:
    """Return a URL template containing ``{trace_id}``, or None if unconfigured.

    Resolution order:
    1. ``STUDIO_TRACE_URL_TEMPLATE`` (must contain ``{trace_id}``) — operator
       override; recommended primary path because Phoenix UI URL paths vary
       across versions/deployments.
    2. Phoenix auto-construction when ``TRACING`` mentions phoenix or
       ``PHOENIX_COLLECTOR_ENDPOINT`` is set. Uses the ``/redirects/traces``
       loader, which resolves project-by-otel-trace-id server-side — avoids
       needing the project's Relay GlobalID (the UI's
       ``/projects/{globalId}/traces/{trace_id}`` route does NOT accept the
       project name).
    3. Langfuse auto-construction when ``TRACING`` mentions langfuse or
       ``LANGFUSE_PUBLIC_KEY`` is set. Stable across versions.
    """
    template = os.getenv("STUDIO_TRACE_URL_TEMPLATE")
    if template and "{trace_id}" in template:
        return template

    enabled = os.getenv("TRACING", "").lower()

    if "phoenix" in enabled or os.getenv("PHOENIX_COLLECTOR_ENDPOINT"):
        ep = os.getenv(
            "PHOENIX_COLLECTOR_ENDPOINT", "http://127.0.0.1:6006/v1/traces"
        )
        ui_base = ep.split("/v1/traces")[0].rstrip("/")
        return f"{ui_base}/redirects/traces/{{trace_id}}"

    if "langfuse" in enabled or os.getenv("LANGFUSE_PUBLIC_KEY"):
        host = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com").rstrip("/")
        return f"{host}/trace/{{trace_id}}"

    return None
