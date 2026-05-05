"""Plugin Protocol — Lifecycle specialization for user-selectable features.

A ``Plugin`` is structurally identical to ``Lifecycle`` (see
``lifecycle.py``); the distinct name marks intent: this component is
**optional and user-selectable**. Core runtime pieces (agents subsystem,
tracing, …) are *not* plugins — they implement ``Lifecycle`` directly
and are auto-loaded by ``Bootstrap``.

Bootstrap accepts a ``list[Lifecycle]`` of plugins; the mandatory core
lifecycle components are added by Bootstrap itself.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .lifecycle import BaseLifecycle, Lifecycle


@runtime_checkable
class Plugin(Lifecycle, Protocol):
    """Optional, user-selectable feature. Same lifecycle as ``Lifecycle``.

    Hosts pass a list of plugins to ``Bootstrap``. Future third-party
    plugins can be discovered via ``importlib.metadata`` entry_points
    without changes here.
    """


class BasePlugin(BaseLifecycle):
    """Convenience base for plugin classes. No new methods — the name
    distinction is purely semantic; structurally a plugin is a Lifecycle
    component.
    """
