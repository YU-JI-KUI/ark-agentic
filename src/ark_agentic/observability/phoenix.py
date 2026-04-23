"""Phoenix observability provider."""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from ..core.callbacks import RunnerCallbacks
from .tracing import create_tracing_callbacks, get_tracer, start_span as _otel_start_span

logger = logging.getLogger(__name__)

_PHOENIX_PROVIDER: Any | None = None
_PHOENIX_INITIALIZED = False


def _env_flag(name: str, *, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class PhoenixProvider:
    """Provider adapter for Phoenix/OpenTelemetry."""

    name = "phoenix"

    def initialize(self, *, service_name: str = "ark-agentic") -> Any | None:
        return init_phoenix(service_name=service_name)

    def shutdown(self) -> None:
        shutdown_phoenix()

    def create_callbacks(
        self,
        *,
        agent_id: str | None = None,
        agent_name: str | None = None,
    ) -> RunnerCallbacks:
        return create_tracing_callbacks(agent_id=agent_id, agent_name=agent_name)

    @contextmanager
    def start_span(
        self,
        name: str,
        *,
        attributes: dict[str, Any] | None = None,
        tracer_name: str = "ark_agentic",
    ) -> Iterator[Any | None]:
        with _otel_start_span(
            name,
            attributes=attributes,
            tracer_name=tracer_name,
        ) as span:
            yield span


def init_phoenix(*, service_name: str = "ark-agentic") -> Any | None:
    """Initialize Phoenix tracing once per process."""
    global _PHOENIX_INITIALIZED, _PHOENIX_PROVIDER

    if _PHOENIX_INITIALIZED:
        return _PHOENIX_PROVIDER
    _PHOENIX_INITIALIZED = True

    try:
        from phoenix.otel import register
    except ImportError:
        logger.warning(
            "Phoenix observability is selected, but dependencies are missing. "
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
        "Phoenix observability enabled project=%s endpoint=%s auto_instrument=%s batch=%s",
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


@contextmanager
def start_span(
    name: str,
    *,
    attributes: dict[str, Any] | None = None,
    tracer_name: str = "ark_agentic",
) -> Iterator[Any | None]:
    with _otel_start_span(
        name,
        attributes=attributes,
        tracer_name=tracer_name,
    ) as span:
        yield span


__all__ = [
    "PhoenixProvider",
    "create_tracing_callbacks",
    "get_tracer",
    "init_phoenix",
    "shutdown_phoenix",
    "start_span",
]
