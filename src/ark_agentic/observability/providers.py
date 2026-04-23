"""Provider selection and public observability facade."""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Protocol

from ..core.callbacks import RunnerCallbacks
from .langfuse import LangfuseProvider
from .phoenix import PhoenixProvider

logger = logging.getLogger(__name__)

_DEFAULT_PROVIDER = "phoenix"
_ACTIVE_PROVIDER: ObservabilityProvider | None = None


class ObservabilityProvider(Protocol):
    name: str

    def initialize(self, *, service_name: str = "ark-agentic") -> Any | None:
        ...

    def shutdown(self) -> None:
        ...

    def create_callbacks(
        self,
        *,
        agent_id: str | None = None,
        agent_name: str | None = None,
    ) -> RunnerCallbacks:
        ...

    def start_span(
        self,
        name: str,
        *,
        attributes: dict[str, Any] | None = None,
        tracer_name: str = "ark_agentic",
    ) -> Iterator[Any | None]:
        ...


def _env_flag(name: str, *, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def observability_enabled() -> bool:
    """Return whether observability is enabled by the generic env flag."""
    return _env_flag("ENABLE_OBSERVABILITY")


def selected_observability_provider() -> str:
    raw = os.getenv("OBSERVABILITY_PROVIDER", _DEFAULT_PROVIDER)
    provider = raw.strip().lower() if raw else _DEFAULT_PROVIDER
    return provider or _DEFAULT_PROVIDER


def _provider_factories() -> dict[str, type[ObservabilityProvider]]:
    return {
        PhoenixProvider.name: PhoenixProvider,
        LangfuseProvider.name: LangfuseProvider,
    }


def _get_provider() -> ObservabilityProvider:
    global _ACTIVE_PROVIDER

    provider_name = selected_observability_provider()
    factories = _provider_factories()
    provider_factory = factories.get(provider_name)
    if provider_factory is None:
        supported = ", ".join(sorted(factories))
        raise ValueError(
            f"Unsupported observability provider: {provider_name}. "
            f"Supported providers: {supported}."
        )

    if _ACTIVE_PROVIDER is not None and _ACTIVE_PROVIDER.name != provider_name:
        _ACTIVE_PROVIDER.shutdown()
        _ACTIVE_PROVIDER = None
    if _ACTIVE_PROVIDER is None:
        _ACTIVE_PROVIDER = provider_factory()
    return _ACTIVE_PROVIDER


def _compose_callbacks(
    internal: RunnerCallbacks,
    external: RunnerCallbacks | None,
) -> RunnerCallbacks:
    external = external or RunnerCallbacks()
    return RunnerCallbacks(
        before_agent=[*internal.before_agent, *external.before_agent],
        after_agent=[*external.after_agent, *internal.after_agent],
        before_model=[*internal.before_model, *external.before_model],
        after_model=[*external.after_model, *internal.after_model],
        before_tool=[*internal.before_tool, *external.before_tool],
        after_tool=[*external.after_tool, *internal.after_tool],
        before_loop_end=[*external.before_loop_end, *internal.before_loop_end],
    )


def build_observability_callbacks(
    *,
    agent_id: str,
    agent_name: str,
    callbacks: RunnerCallbacks | None = None,
) -> RunnerCallbacks:
    """Compose provider tracing callbacks with caller-provided runner callbacks."""
    if not observability_enabled():
        return callbacks or RunnerCallbacks()

    provider = _get_provider()
    tracing_callbacks = provider.create_callbacks(
        agent_id=agent_id,
        agent_name=agent_name,
    )
    return _compose_callbacks(tracing_callbacks, callbacks)


def init_observability(*, service_name: str = "ark-agentic") -> Any | None:
    """Initialize the selected observability provider when enabled."""
    if not observability_enabled():
        logger.info("Observability disabled")
        return None
    return _get_provider().initialize(service_name=service_name)


def shutdown_observability() -> None:
    global _ACTIVE_PROVIDER

    provider = _ACTIVE_PROVIDER
    _ACTIVE_PROVIDER = None
    if provider is None:
        return
    provider.shutdown()


@contextmanager
def start_span(
    name: str,
    *,
    attributes: dict[str, Any] | None = None,
    tracer_name: str = "ark_agentic",
) -> Iterator[Any | None]:
    """Start a best-effort provider span and no-op when observability is disabled."""
    if not observability_enabled():
        yield None
        return
    provider = _get_provider()
    with provider.start_span(
        name,
        attributes=attributes,
        tracer_name=tracer_name,
    ) as span:
        yield span


__all__ = [
    "build_observability_callbacks",
    "init_observability",
    "observability_enabled",
    "selected_observability_provider",
    "shutdown_observability",
    "start_span",
]
