"""Console tracing provider — prints span output to stdout for local dev."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class ConsoleProvider:
    name = "console"

    def __init__(self) -> None:
        self._processor: Any | None = None

    def has_credentials(self) -> bool:
        # Too noisy to auto-enable. Must be listed explicitly in TRACING.
        return False

    def install(self, tp: Any) -> None:
        from opentelemetry.sdk.trace.export import (
            ConsoleSpanExporter,
            SimpleSpanProcessor,
        )

        self._processor = SimpleSpanProcessor(ConsoleSpanExporter())
        tp.add_span_processor(self._processor)
        logger.info("Console exporter installed (stdout)")

    def shutdown(self) -> None:
        if self._processor is not None:
            self._processor.shutdown()
            self._processor = None
