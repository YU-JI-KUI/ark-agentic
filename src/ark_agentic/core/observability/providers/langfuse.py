"""Langfuse tracing provider — Langfuse OTLP endpoint with basic-auth headers."""

from __future__ import annotations

import base64
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


class LangfuseProvider:
    name = "langfuse"

    def __init__(self) -> None:
        self._processor: Any | None = None

    def has_credentials(self) -> bool:
        return bool(
            os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY")
        )

    def install(self, tp: Any) -> None:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        host = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com").rstrip("/")
        endpoint = f"{host}/api/public/otel/v1/traces"
        public_key = os.environ["LANGFUSE_PUBLIC_KEY"]
        secret_key = os.environ["LANGFUSE_SECRET_KEY"]
        auth = base64.b64encode(f"{public_key}:{secret_key}".encode()).decode()
        self._processor = BatchSpanProcessor(
            OTLPSpanExporter(
                endpoint=endpoint,
                headers={"Authorization": f"Basic {auth}"},
            )
        )
        tp.add_span_processor(self._processor)
        logger.info("Langfuse exporter installed host=%s", host)

    def shutdown(self) -> None:
        if self._processor is not None:
            self._processor.shutdown()
            self._processor = None
