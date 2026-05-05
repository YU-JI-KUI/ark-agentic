"""Composition primitives — Lifecycle/Plugin protocols, Bootstrap driver,
AppContext container.

These are the *contracts* around which the framework's runtime is
organised. Concrete Lifecycle implementations live in ``core.runtime``.
"""

from .bootstrap import Bootstrap, default_lifecycle_components
from .context import AppContext
from .lifecycle import BaseLifecycle, Lifecycle
from .plugin import BasePlugin, Plugin

__all__ = [
    "AppContext",
    "BaseLifecycle",
    "BasePlugin",
    "Bootstrap",
    "Lifecycle",
    "Plugin",
    "default_lifecycle_components",
]
