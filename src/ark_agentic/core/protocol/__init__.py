"""Composition primitives — Lifecycle/Plugin protocols, Bootstrap driver,
AppContext container.

These are the *contracts* around which the framework's runtime is
organised. Concrete Lifecycle implementations live in ``core.runtime``.
"""

from .app_context import AppContext
from .bootstrap import Bootstrap
from .lifecycle import BaseLifecycle, Lifecycle
from .plugin import BasePlugin, Plugin

__all__ = [
    "AppContext",
    "BaseLifecycle",
    "BasePlugin",
    "Bootstrap",
    "Lifecycle",
    "Plugin",
]
