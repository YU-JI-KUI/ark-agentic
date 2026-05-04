"""Plugin Protocol — Lifecycle specialization for user-selectable features.

A ``Plugin`` is structurally identical to ``Lifecycle`` (see
``core/lifecycle.py``); the distinct name marks intent: this component is
**optional and user-selectable** (CLI scaffolds and deployments choose
to include or omit it). Core runtime pieces (agents subsystem, tracing,
…) are *not* plugins — they implement ``Lifecycle`` directly.

Bootstrap accepts ``list[Lifecycle]``; plugins are simply a subset of
the components it orchestrates.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .lifecycle import BaseLifecycle, Lifecycle


@runtime_checkable
class Plugin(Lifecycle, Protocol):
    """Optional, user-selectable feature. Same lifecycle as ``Lifecycle``.

    Hosts register plugins in a static list (e.g. ``DEFAULT_PLUGINS`` in
    ``ark_agentic.bootstrap``); future third-party plugins can be loaded
    via ``importlib.metadata`` entry_points without changes here.
    """


class BasePlugin(BaseLifecycle):
    """Convenience base for plugin classes. No new methods — the name
    distinction is purely semantic; structurally a plugin is a Lifecycle
    component.
    """
