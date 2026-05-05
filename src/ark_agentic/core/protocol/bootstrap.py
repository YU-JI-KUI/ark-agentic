"""Bootstrap — drives a list of Lifecycle components through init/start/stop.

Stateful orchestrator. Hosts (FastAPI ``app.py``, CLI scaffolds, tests)
build a Bootstrap with their chosen plugins; the always-on lifecycle
components (``AgentsRuntime``, ``TracingLifecycle``) are auto-loaded by
this module and cannot be deselected by callers.

Phases:

- ``init`` — one-time setup (schema creation, dirs). Re-callable; only
  runs once per Bootstrap instance.
- ``start(ctx)`` — calls ``init`` first (idempotent), then runs
  ``start(ctx)`` on every component in registration order, attaching
  any returned value to ``ctx.{name}`` so later components can read it.
- ``stop`` — runs ``stop`` on every started component in **reverse**
  order. Per-component try/except prevents a failing teardown from
  blocking the rest.

``install_routes(app)`` is the orthogonal HTTP-mount hook, called at
module-load time (before lifespan starts).

The class is HTTP-agnostic: it never imports FastAPI nor knows about
``app.state`` or ``yield``. Hosts that need a FastAPI lifespan write
their own thin wrapper — typically::

    @asynccontextmanager
    async def lifespan(app):
        ctx = AppContext()
        await bootstrap.start(ctx)
        app.state.ctx = ctx
        try:
            yield
        finally:
            await bootstrap.stop()
"""

from __future__ import annotations

import logging
from typing import Any

from .lifecycle import Lifecycle

logger = logging.getLogger(__name__)


def default_lifecycle_components() -> list[Lifecycle]:
    """Always-on framework components — agents registry + tracing.

    Returns a fresh list of new instances on each call. Order matters:
    agents first (registry must be ready before any plugin's ``start``
    runs), tracing last (so a tracing failure can't block earlier
    components from starting / stopping).

    Imported lazily to keep the protocol package free of concrete-
    runtime imports at module load time.
    """
    from ..observability.lifecycle import TracingLifecycle
    from ..runtime.agents_runtime import AgentsRuntime
    return [AgentsRuntime(), TracingLifecycle()]


class Bootstrap:
    """Filters disabled components at construction; remembers which ones
    successfully started so ``stop`` only tears down what really started.

    Public API: pass ``plugins`` (the user-selectable lifecycle list).
    The mandatory defaults (``AgentsRuntime`` + ``TracingLifecycle``)
    are prepended / appended automatically. Tests that need to exercise
    Bootstrap mechanics with arbitrary recorders can pass
    ``with_defaults=False``.
    """

    def __init__(
        self,
        plugins: list[Lifecycle] | None = None,
        *,
        with_defaults: bool = True,
    ) -> None:
        if with_defaults:
            defaults = default_lifecycle_components()
            agents, tracing = defaults[0], defaults[-1]
            components: list[Lifecycle] = [agents] + list(plugins or []) + [tracing]
        else:
            components = list(plugins or [])
        self._components: list[Lifecycle] = [
            c for c in components if c.is_enabled()
        ]
        self._started: list[Lifecycle] = []
        self._inited = False

    @property
    def components(self) -> tuple[Lifecycle, ...]:
        """Read-only view of the enabled components in registration order."""
        return tuple(self._components)

    async def init(self) -> None:
        """Run ``init()`` on every enabled component once.

        Idempotent: subsequent calls are no-ops. ``start`` calls this
        first so most hosts never invoke ``init`` directly; tests that
        only want to exercise schema setup can call it standalone.
        """
        if self._inited:
            return
        for c in self._components:
            await c.init()
            logger.debug("Component %r init() complete", c.name)
        self._inited = True

    def install_routes(self, app: Any) -> None:
        """Run ``install_routes(app)`` on every enabled component.

        Components that don't expose HTTP are no-ops (BaseLifecycle
        default), so this is safe to call uniformly.
        """
        for c in self._components:
            c.install_routes(app)
            logger.debug("Component %r install_routes() complete", c.name)

    async def start(self, ctx: Any) -> None:
        """Init (if not already), then build runtime context across components.

        The non-``None`` return value of each ``start`` is attached to
        ``ctx.{name}`` so components started later can read it (e.g.
        JobsPlugin reading ``ctx.notifications``).
        """
        await self.init()
        for c in self._components:
            value = await c.start(ctx)
            if value is not None:
                setattr(ctx, c.name, value)
            self._started.append(c)
            logger.info("Component %r started", c.name)

    async def stop(self) -> None:
        """Run ``stop()`` on every started component in **reverse** order.

        Per-component try/except so a failing teardown cannot block the
        rest from releasing their resources.
        """
        while self._started:
            c = self._started.pop()
            try:
                await c.stop()
                logger.info("Component %r stopped", c.name)
            except Exception:
                logger.exception("Component %r stop() failed", c.name)
