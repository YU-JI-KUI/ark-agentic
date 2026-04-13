"""Phoenix/OpenTelemetry integration helpers."""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

logger = logging.getLogger(__name__)

_PHOENIX_PROVIDER: Any | None = None
_PHOENIX_INITIALIZED = False


def _env_flag(name: str, *, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _phoenix_enabled() -> bool:
    if "ENABLE_PHOENIX" in os.environ:
        return _env_flag("ENABLE_PHOENIX")
    return any(
        os.getenv(name)
        for name in (
            "PHOENIX_COLLECTOR_ENDPOINT",
            "PHOENIX_PROJECT_NAME",
            "PHOENIX_API_KEY",
            "PHOENIX_CLIENT_HEADERS",
        )
    )


def init_phoenix(*, service_name: str = "ark-agentic") -> Any | None:
    """Initialize Phoenix tracing once per process."""
    global _PHOENIX_INITIALIZED, _PHOENIX_PROVIDER

    if _PHOENIX_INITIALIZED:
        return _PHOENIX_PROVIDER
    _PHOENIX_INITIALIZED = True

    if not _phoenix_enabled():
        logger.info("Phoenix tracing disabled")
        return None

    try:
        from phoenix.otel import register
    except ImportError:
        logger.warning(
            "Phoenix tracing is enabled by env, but dependencies are missing. "
            "Install 'arize-phoenix-otel' and 'openinference-instrumentation-langchain'."
        )
        return None

    kwargs: dict[str, Any] = {
        "batch": _env_flag("PHOENIX_BATCH", default=True),
        "auto_instrument": _env_flag("PHOENIX_AUTO_INSTRUMENT", default=True),
        "project_name": os.getenv("PHOENIX_PROJECT_NAME", service_name),
    }
    protocol = os.getenv("PHOENIX_PROTOCOL", "").strip()
    if protocol:
        kwargs["protocol"] = protocol
    endpoint = os.getenv("PHOENIX_COLLECTOR_ENDPOINT", "").strip()
    if endpoint:
        kwargs["endpoint"] = endpoint

    _PHOENIX_PROVIDER = register(**kwargs)
    logger.info(
        "Phoenix tracing enabled project=%s endpoint=%s auto_instrument=%s batch=%s",
        kwargs["project_name"],
        endpoint or "env/default",
        kwargs["auto_instrument"],
        kwargs["batch"],
    )
    return _PHOENIX_PROVIDER


def shutdown_phoenix() -> None:
    global _PHOENIX_PROVIDER, _PHOENIX_INITIALIZED

    provider = _PHOENIX_PROVIDER
    _PHOENIX_PROVIDER = None
    _PHOENIX_INITIALIZED = False
    if provider is None:
        return
    shutdown = getattr(provider, "shutdown", None)
    if callable(shutdown):
        shutdown()
        logger.info("Phoenix tracer provider shut down")


def get_tracer(name: str) -> Any | None:
    try:
        from opentelemetry import trace
    except ImportError:
        return None
    return trace.get_tracer(name)


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
        if attributes:
            for key, value in attributes.items():
                if value is None:
                    continue
                if isinstance(value, (str, bool, int, float)):
                    span.set_attribute(key, value)
                else:
                    span.set_attribute(key, str(value))
        yield span
