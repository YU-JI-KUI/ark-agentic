"""TracingRuntime — OpenTelemetry tracing as a Lifecycle component.

Pairs ``setup_tracing_from_env`` (start) with ``shutdown_tracing`` (stop)
so they cannot get out of sync. Service name is read from env so the
runtime can also be reused by CLI / worker hosts.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from ..protocol.lifecycle import BaseLifecycle
from ..observability import setup_tracing_from_env, shutdown_tracing

logger = logging.getLogger(__name__)


class TracingRuntime(BaseLifecycle):
    """OTLP tracing setup + shutdown."""

    name = "tracing"

    def __init__(self, service_name: str | None = None) -> None:
        self._service_name = (
            service_name or os.getenv("OTEL_SERVICE_NAME") or "ark-agentic-api"
        )
        self._provider: Any = None

    async def start(self, ctx: Any) -> None:
        self._provider = setup_tracing_from_env(service_name=self._service_name)
        logger.debug("Tracing started (service=%s)", self._service_name)
        # Return None — tracing has no value to publish on AppContext.

    async def stop(self) -> None:
        if self._provider is not None:
            shutdown_tracing(self._provider)
            self._provider = None
            logger.debug("Tracing shutdown complete")
