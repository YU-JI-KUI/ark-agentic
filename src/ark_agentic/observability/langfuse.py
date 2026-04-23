"""Langfuse observability provider."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from ..core.callbacks import RunnerCallbacks
from .tracing import create_tracing_callbacks, start_span as _otel_start_span

logger = logging.getLogger(__name__)

_LANGFUSE_CLIENT: Any | None = None
_LANGFUSE_INITIALIZED = False


def _should_export_span(_span: Any) -> bool:
    """Export Ark runner spans emitted through OpenTelemetry to Langfuse."""
    return True


class LangfuseProvider:
    """Provider adapter for Langfuse SDK v4 OpenTelemetry export."""

    name = "langfuse"

    def initialize(self, *, service_name: str = "ark-agentic") -> Any | None:
        return init_langfuse(service_name=service_name)

    def shutdown(self) -> None:
        shutdown_langfuse()

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


def init_langfuse(*, service_name: str = "ark-agentic") -> Any | None:
    """Initialize Langfuse once per process."""
    global _LANGFUSE_CLIENT, _LANGFUSE_INITIALIZED

    if _LANGFUSE_INITIALIZED:
        return _LANGFUSE_CLIENT
    _LANGFUSE_INITIALIZED = True

    try:
        from langfuse import Langfuse
    except ImportError:
        try:
            from langfuse import get_client
        except ImportError:
            logger.warning(
                "Langfuse observability is selected, but dependency 'langfuse' "
                "is missing. Install 'langfuse'."
            )
            return None
        _LANGFUSE_CLIENT = get_client()
    else:
        _LANGFUSE_CLIENT = Langfuse(should_export_span=_should_export_span)

    logger.info("Langfuse observability enabled service=%s", service_name)
    return _LANGFUSE_CLIENT


def shutdown_langfuse() -> None:
    global _LANGFUSE_CLIENT, _LANGFUSE_INITIALIZED

    client = _LANGFUSE_CLIENT
    _LANGFUSE_CLIENT = None
    _LANGFUSE_INITIALIZED = False
    if client is None:
        return
    shutdown = getattr(client, "shutdown", None)
    if callable(shutdown):
        shutdown()
        logger.info("Langfuse client shut down")
        return
    flush = getattr(client, "flush", None)
    if callable(flush):
        flush()
        logger.info("Langfuse client flushed")


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
    "LangfuseProvider",
    "init_langfuse",
    "shutdown_langfuse",
    "start_span",
]
