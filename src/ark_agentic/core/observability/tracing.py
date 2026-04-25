"""Tracing setup / shutdown — env-driven multi-provider OTel pipeline.

Single env var ``TRACING`` selects the active providers:

  TRACING=console                 # local dev — print spans to stdout
  TRACING=phoenix                 # Phoenix collector
  TRACING=langfuse                # Langfuse cloud
  TRACING=phoenix,langfuse        # dual export
  TRACING=otlp                    # generic OTLP via OTEL_EXPORTER_OTLP_ENDPOINT
  TRACING=auto                    # every provider whose credentials are set

Unset (or empty) → tracing disabled, OTel NoOp tracer makes all decorator
spans zero-cost.

LangChain auto-instrumentation (openinference-instrumentation-langchain) is
enabled whenever any provider is enabled, so ChatOpenAI calls produce
streaming-token / parameter / usage spans automatically.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider

from .providers import PROVIDERS, TracingProvider

logger = logging.getLogger(__name__)


def _resolve_enabled_providers() -> list[str]:
    """Return the provider name list selected by the TRACING env var."""
    spec = os.getenv("TRACING", "").strip().lower()
    if not spec:
        return []
    if spec == "auto":
        return [
            name for name, cls in PROVIDERS.items() if cls().has_credentials()
        ]
    names = [n.strip() for n in spec.split(",") if n.strip()]
    unknown = [n for n in names if n not in PROVIDERS]
    if unknown:
        logger.warning(
            "Unknown tracing providers in TRACING=%s: %s (available: %s)",
            spec,
            unknown,
            list(PROVIDERS),
        )
    return [n for n in names if n in PROVIDERS]


def setup_tracing_from_env(
    *, service_name: str = "ark-agentic"
) -> TracerProvider | None:
    """Configure the global TracerProvider with all enabled providers.

    Idempotent across cold starts; not safe for re-entry within one process
    (caller should hold the returned provider for shutdown).
    """
    enabled_names = _resolve_enabled_providers()
    if not enabled_names:
        logger.info("Tracing disabled (TRACING env not set)")
        return None

    tp = TracerProvider(resource=Resource.create({"service.name": service_name}))
    instances: list[TracingProvider] = []
    for name in enabled_names:
        provider = PROVIDERS[name]()
        try:
            provider.install(tp)
        except Exception as e:
            logger.error("Failed to install tracing provider %s: %s", name, e)
            continue
        instances.append(provider)
        logger.info("Tracing provider enabled: %s", name)
    trace.set_tracer_provider(tp)

    # LangChain auto-instrumentation — captures ChatOpenAI internals
    # (streaming token, invocation params, usage) as child spans of whatever
    # ark span is active. Free LLM observability with one line.
    try:
        from openinference.instrumentation.langchain import LangChainInstrumentor

        LangChainInstrumentor().instrument(tracer_provider=tp)
        logger.info("LangChain auto-instrumentation enabled")
    except ImportError:  # pragma: no cover
        logger.warning(
            "openinference-instrumentation-langchain not installed; "
            "LLM-internal spans will be missing"
        )
    except Exception as e:  # pragma: no cover
        logger.warning("Failed to enable LangChain auto-instrumentation: %s", e)

    tp._ark_providers = instances  # type: ignore[attr-defined]
    return tp


def shutdown_tracing(tp: TracerProvider | None) -> None:
    """Flush + shut down all installed provider processors."""
    if tp is None:
        return
    for provider in getattr(tp, "_ark_providers", []):
        try:
            provider.shutdown()
        except Exception as e:
            logger.warning("Error shutting down provider %s: %s", provider.name, e)
    shutdown = getattr(tp, "shutdown", None)
    if callable(shutdown):
        shutdown()


def get_tracer(name: str) -> Any:
    """Convenience accessor — returns the global tracer for ``name``."""
    return trace.get_tracer(name)
