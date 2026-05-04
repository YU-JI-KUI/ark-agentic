"""Lifecycle Protocol — uniform contract for orchestrated app components.

Distinguishes two roles in this codebase:

- ``Lifecycle`` is the base contract: any component the host
  (``Bootstrap``) drives through the standard init → start → stop
  sequence. Used by core runtime pieces (agents subsystem, tracing,
  …) that are **always part of the app**, not pluggable.
- ``Plugin`` extends ``Lifecycle`` (see ``core/plugin.py``) for
  **optional, user-selectable features**. Same lifecycle methods,
  different semantic role.

The split keeps composition uniform (one Bootstrap, one for-loop) while
letting names honour the difference: agents are core capability, not
plugins.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Lifecycle(Protocol):
    """Component the host orchestrates through init/start/stop.

    All methods have no-op defaults via ``BaseLifecycle`` so concrete
    components only override the phases they actually use.
    """

    name: str
    """Identifier used as the AppContext field name + log identifier."""

    def is_enabled(self) -> bool:
        """Env-driven on/off gate. Disabled components are skipped entirely."""
        ...

    async def init(self) -> None:
        """One-time idempotent setup (schema creation, directory layout, …)."""
        ...

    def install_routes(self, app: Any) -> None:
        """Mount HTTP routes / middleware on the FastAPI app.

        Module-load time, before lifespan starts. Non-HTTP components
        leave this as a no-op.
        """
        ...

    async def start(self, ctx: Any) -> Any:
        """Build runtime context and start background tasks.

        The non-``None`` return value is attached to ``ctx.{name}`` by
        Bootstrap so other components started later can read it.
        """
        ...

    async def stop(self) -> None:
        """Stop background tasks, release resources.

        Bootstrap calls ``stop`` in **reverse** start order so that
        dependencies remain available throughout each component's
        teardown.
        """
        ...


class BaseLifecycle:
    """No-op default implementation. Concrete components subclass this and
    override only the phases they need.

    Subclasses MUST set ``name`` to a non-empty string.
    """

    name: str = ""

    def is_enabled(self) -> bool:
        return True

    async def init(self) -> None:
        return None

    def install_routes(self, app: Any) -> None:
        return None

    async def start(self, ctx: Any) -> Any:
        return None

    async def stop(self) -> None:
        return None
