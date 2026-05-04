"""Bootstrap — drives a list of Lifecycle components through init/start/stop.

Hosts (FastAPI ``app.py``, CLI scaffolds, tests) construct a Bootstrap
with their chosen component list and call its lifecycle methods. The
class is HTTP-agnostic: ``install_routes`` is the only FastAPI-touching
method, and even that takes the app as a plain ``Any``.

Phase semantics:

- ``init_all``           one-time idempotent setup (schema creation, dirs)
- ``install_routes``     module-load HTTP route / middleware mounting
- ``start_all``          build runtime ctx values; populate ``ctx.{name}``
- ``stop_all``           reverse-order teardown; per-component try/except
- ``lifespan(app, ctx)`` async context manager combining the above for
                         FastAPI's ``lifespan=`` parameter
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from .lifecycle import Lifecycle

logger = logging.getLogger(__name__)


class Bootstrap:
    """Stateful orchestrator. Filters disabled components at construction
    time and remembers which ones successfully started so ``stop_all``
    only tears down what actually started."""

    def __init__(self, components: list[Lifecycle]) -> None:
        self._components: list[Lifecycle] = [
            c for c in components if c.is_enabled()
        ]
        self._started: list[Lifecycle] = []

    @property
    def components(self) -> tuple[Lifecycle, ...]:
        """Read-only view of the enabled components in registration order."""
        return tuple(self._components)

    async def init_all(self) -> None:
        """Run ``init()`` on every enabled component, in order."""
        for c in self._components:
            await c.init()
            logger.debug("Component %r init() complete", c.name)

    def install_routes(self, app: Any) -> None:
        """Run ``install_routes(app)`` on every enabled component.

        Components that don't expose HTTP are no-ops (BaseLifecycle
        default), so this is safe to call uniformly.
        """
        for c in self._components:
            c.install_routes(app)
            logger.debug("Component %r install_routes() complete", c.name)

    async def start_all(self, ctx: Any) -> None:
        """Run ``start(ctx)`` on every enabled component, in order.

        The non-``None`` return value is attached to ``ctx.{name}`` so
        components started later can read it (e.g. JobsRuntime reading
        ``ctx.notifications``).
        """
        for c in self._components:
            value = await c.start(ctx)
            if value is not None:
                setattr(ctx, c.name, value)
            self._started.append(c)
            logger.info("Component %r started", c.name)

    async def stop_all(self) -> None:
        """Run ``stop()`` on every started component, **reverse order**.

        Each ``stop`` is wrapped in try/except so a failing component
        cannot block the rest from cleaning up.
        """
        while self._started:
            c = self._started.pop()
            try:
                await c.stop()
                logger.info("Component %r stopped", c.name)
            except Exception:
                logger.exception("Component %r stop() failed", c.name)

    @asynccontextmanager
    async def lifespan(self, app: Any, ctx: Any) -> AsyncIterator[None]:
        """One-call lifespan for FastAPI hosts.

        Equivalent to::

            await bootstrap.init_all()
            await bootstrap.start_all(ctx)
            app.state.ctx = ctx
            try: yield
            finally: await bootstrap.stop_all()
        """
        await self.init_all()
        try:
            await self.start_all(ctx)
            app.state.ctx = ctx
            yield
        finally:
            await self.stop_all()
