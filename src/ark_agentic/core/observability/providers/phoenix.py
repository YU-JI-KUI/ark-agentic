"""Phoenix tracing provider — uses OTLP exporter against the Phoenix collector."""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

def _env_flag(name: str, *, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}

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
        from phoenix.otel import register

        kwargs: dict[str, Any] = {
            "batch": _env_flag("PHOENIX_BATCH", default=True),
            "auto_instrument": _env_flag("PHOENIX_AUTO_INSTRUMENT", default=True),
            "project_name": os.getenv("PHOENIX_PROJECT_NAME", "ark-agentic"),
        }

        protocol = os.getenv("PHOENIX_PROTOCOL", "").strip()
        if protocol:
            kwargs["protocol"] = protocol

        endpoint = os.getenv(
            "PHOENIX_COLLECTOR_ENDPOINT", "http://127.0.0.1:6006/v1/traces"
        )
        if endpoint:
            kwargs["endpoint"] = endpoint

        register(**kwargs)

        self._processor = BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint))
        tp.add_span_processor(self._processor)
        logger.info(
            "Phoenix tracing enabled project=%s endpoint=%s auto_instrument=%s batch=%s",
            kwargs["project_name"],
            endpoint or "env/default",
            kwargs["auto_instrument"],
            kwargs["batch"],
        )

    def shutdown(self) -> None:
        if self._processor is not None:
            self._processor.shutdown()
            self._processor = None
