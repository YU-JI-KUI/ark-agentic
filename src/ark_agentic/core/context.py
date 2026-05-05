"""AppContext — runtime container populated by Lifecycle components.

``Bootstrap.start()`` walks the registered ``Lifecycle`` components and,
for each one whose ``start()`` returns a non-``None`` value, calls
``setattr(ctx, component.name, value)``. Consumers retrieve those
attributes by name — defensively, since a component may be disabled and
therefore never publish itself.

Kept generic on purpose: ``core/`` must not encode the names of optional
features. Plugins do not type-hint their slots here — they read back via
``getattr(ctx, "<name>", None)`` and apply local typing.
"""

from __future__ import annotations


class AppContext:
    """Empty namespace; attributes are attached at runtime by Bootstrap."""
