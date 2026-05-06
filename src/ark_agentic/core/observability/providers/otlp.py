"""Generic OTLP tracing provider — exports to any OTel collector via standard env."""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


class OTLPProvider:
    name = "otlp"

    def __init__(self) -> None:
        self._processor: Any | None = None

    def has_credentials(self) -> bool:
        return bool(os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"))

    def install(self, tp: Any) -> None:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        # OTLPSpanExporter() with no args reads OTEL_EXPORTER_OTLP_ENDPOINT,
        # OTEL_EXPORTER_OTLP_HEADERS, etc. from the environment automatically.
        self._processor = BatchSpanProcessor(OTLPSpanExporter())
        tp.add_span_processor(self._processor)
        logger.info(
            "OTLP exporter installed endpoint=%s",
            os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"),
        )

    def shutdown(self) -> None:
        if self._processor is not None:
            self._processor.shutdown()
            self._processor = None
