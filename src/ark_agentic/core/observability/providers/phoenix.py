"""Phoenix tracing provider — uses OTLP exporter against the Phoenix collector."""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


class PhoenixProvider:
    name = "phoenix"

    def __init__(self) -> None:
        self._processor: Any | None = None

    def has_credentials(self) -> bool:
        # Auto-mode requires explicit endpoint to avoid spamming dev machines
        # that don't have Phoenix running on localhost:6006.
        return bool(os.getenv("PHOENIX_COLLECTOR_ENDPOINT"))

    def install(self, tp: Any) -> None:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        endpoint = os.getenv(
            "PHOENIX_COLLECTOR_ENDPOINT", "http://127.0.0.1:6006/v1/traces"
        )
        self._processor = BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint))
        tp.add_span_processor(self._processor)
        logger.info("Phoenix exporter installed endpoint=%s", endpoint)

    def shutdown(self) -> None:
        if self._processor is not None:
            self._processor.shutdown()
            self._processor = None
