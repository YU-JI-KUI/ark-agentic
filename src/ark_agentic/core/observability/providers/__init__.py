"""Tracing provider registry — startup-time fan-out to one or more backends.

Adding a new provider:
  1. Create providers/<name>.py with a class implementing TracingProvider.
  2. Add an entry to PROVIDERS below.

The active set is selected by the ``TRACING`` env var (see tracing.py).
"""

from __future__ import annotations

from typing import Any, Callable, Protocol

from .console import ConsoleProvider
from .langfuse import LangfuseProvider
from .otlp import OTLPProvider
from .phoenix import PhoenixProvider


class TracingProvider(Protocol):
    name: str

    def has_credentials(self) -> bool: ...

    def install(self, tp: Any) -> None: ...

    def shutdown(self) -> None: ...


PROVIDERS: dict[str, Callable[[], TracingProvider]] = {
    "phoenix": PhoenixProvider,
    "langfuse": LangfuseProvider,
    "console": ConsoleProvider,
    "otlp": OTLPProvider,
}


__all__ = [
    "PROVIDERS",
    "TracingProvider",
    "ConsoleProvider",
    "LangfuseProvider",
    "OTLPProvider",
    "PhoenixProvider",
]
