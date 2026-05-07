"""Bootstrap — drives a list of Lifecycle components through init/start/stop.

Stateful orchestrator. Hosts (FastAPI ``app.py``, CLI scaffolds) build a
Bootstrap with their chosen plugins; the always-on framework lifecycle
components (``AgentsLifecycle`` first, ``TracingLifecycle`` last) are
auto-loaded by Bootstrap and cannot be deselected. The class is
HTTP-agnostic: it never imports FastAPI nor knows about ``app.state``.

The default lifecycle classes are imported inside ``__init__`` rather
than at module load — runtime/observability transitively pull
``protocol/`` themselves, so a top-level import would cycle. The ``Lifecycle``
and ``Plugin`` Protocols themselves stay free of any concrete imports.

Phases:

- ``init`` — one-time setup (schema creation, dirs). Idempotent.
- ``start(ctx)`` — calls ``init`` first, then ``start(ctx)`` on every
  component in registration order, attaching any non-``None`` return
  value to ``ctx.{name}`` so later components can read it.
- ``stop`` — runs ``stop`` on every started component in **reverse**
  order; per-component try/except so a failing teardown can't block
  the rest.

``install_routes(app)`` is the orthogonal HTTP-mount hook, called at
module-load time (before lifespan starts).

CLI scaffolds with their own agents seed the framework registry through
``Bootstrap.agent_registry`` before ``start()`` runs::

    bootstrap = Bootstrap(components=[APIPlugin(), ...])
    bootstrap.agent_registry.register("default", create_default_agent())
"""

from __future__ import annotations

import inspect
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .lifecycle import Lifecycle

if TYPE_CHECKING:
    from ..runtime.agents_lifecycle import AgentsLifecycle as _AgentsLifecycle
    from ..runtime.registry import AgentRegistry

logger = logging.getLogger(__name__)


class Bootstrap:
    """Filters disabled components at construction; remembers which ones
    successfully started so ``stop`` only tears down what really started.

    Public API: pass the user-selectable ``components`` list. The framework
    defaults — ``CoreStorageLifecycle`` (first), ``AgentsLifecycle``
    (second) and ``TracingLifecycle`` (last) — are added unconditionally;
    their ordering matters and is not configurable. User components sit
    between ``AgentsLifecycle`` and ``TracingLifecycle``.

    Hosts that need to seed agents before start populate
    ``Bootstrap.agent_registry`` directly.
    """

    def __init__(
        self,
        components: list[Lifecycle] | None = None,
        *,
        agents_root: "Path | None" = None,
    ) -> None:
        # Lazy import: runtime + observability transitively import the
        # protocol package, so a top-level import would cycle.
        from ..observability.tracing_lifecycle import TracingLifecycle
        from ..runtime.agents_lifecycle import AgentsLifecycle
        from ..storage.storage_lifecycle import CoreStorageLifecycle

        resolved_root = self._resolve_agents_root(agents_root)
        self._storage: Lifecycle | None = CoreStorageLifecycle()
        self._agents: "_AgentsLifecycle | None" = AgentsLifecycle(
            agents_root=resolved_root,
        )
        self._tracing: Lifecycle | None = TracingLifecycle()
        # Storage runs first so the central session / user-memory tables
        # exist before agents warm up or component init() touches the DB.
        _all: list[Lifecycle] = (
            [self._storage, self._agents]
            + list(components or [])
            + [self._tracing]
        )
        self._components: list[Lifecycle] = [
            c for c in _all if c.is_enabled()
        ]
        self._started: list[Lifecycle] = []
        self._inited = False

    @staticmethod
    def _resolve_agents_root(explicit: Path | None) -> Path | None:
        """Three-tier resolution: explicit > AGENTS_ROOT env > caller convention.

        Convention: caller's source file directory + ``/agents``. The
        "caller" is the *first* non-bootstrap frame on the stack —
        typically the user's ``app.py`` invoking ``Bootstrap(...)``
        directly.

        ⚠️ If a wrapper / factory function instantiates ``Bootstrap`` on
        the user's behalf (e.g. ``def make_app(): return Bootstrap(...)``),
        the convention resolves relative to **the wrapper's** file, not
        the caller's project root. In that case pass ``agents_root=``
        explicitly — only the explicit arg is wrapper-safe; both
        convention and ``AGENTS_ROOT`` work for direct callers.

        Sets ``AGENTS_ROOT`` env var (only if unset) so downstream
        runtime code that needs the path (Studio's filesystem CRUD,
        meta_builder tools) sees the same value the lifecycle uses. The
        resolved path is logged at INFO with its source so misroutes are
        visible.
        """
        if explicit is not None:
            resolved = explicit.resolve()
        elif env := os.getenv("AGENTS_ROOT"):
            resolved = Path(env).resolve()
        else:
            resolved = None
            for frame_info in inspect.stack()[1:]:
                fname = frame_info.filename
                # Skip frames inside this file (the resolver itself).
                if fname == __file__:
                    continue
                candidate = Path(fname).resolve().parent / "agents"
                if candidate.is_dir():
                    resolved = candidate
                    logger.info(
                        "Bootstrap resolved agents_root by convention: %s "
                        "(caller=%s)", candidate, fname,
                    )
                    break
            if resolved is None:
                logger.info(
                    "Bootstrap: no agents_root resolved (no explicit arg, "
                    "no AGENTS_ROOT env, no agents/ dir next to caller)",
                )
                return None

        if "AGENTS_ROOT" not in os.environ:
            os.environ["AGENTS_ROOT"] = str(resolved)
        return resolved

    @classmethod
    def _from_components(cls, components: list[Lifecycle]) -> "Bootstrap":
        """Test-only escape hatch: build a Bootstrap from arbitrary
        recorder lifecycles, bypassing the framework defaults. Production
        code MUST go through the public constructor.
        """
        self = cls.__new__(cls)
        self._storage = None
        self._agents = None  # type: ignore[assignment]
        self._tracing = None  # type: ignore[assignment]
        self._components = [c for c in components if c.is_enabled()]
        self._started = []
        self._inited = False
        return self

    @property
    def components(self) -> tuple[Lifecycle, ...]:
        """Read-only view of the enabled components in registration order."""
        return tuple(self._components)

    @property
    def agent_registry(self) -> AgentRegistry:
        """The framework's pre-start ``AgentRegistry``.

        Hosts populate this before ``start()`` to register their own
        agents. The same instance is published as ``ctx.agent_registry``
        once start runs.
        """
        if self._agents is None:
            raise RuntimeError(
                "Bootstrap was built without defaults (test mode); "
                "no agent_registry is available."
            )
        return self._agents.registry

    async def init(self) -> None:
        """Run ``init()`` on every enabled component once. Idempotent."""
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
        ``ctx.{name}``. Two components publishing the same name is a
        configuration error and raises immediately.
        """
        await self.init()
        for c in self._components:
            value = await c.start(ctx)
            if value is not None:
                if hasattr(ctx, c.name) and getattr(ctx, c.name) is not None:
                    raise RuntimeError(
                        f"Lifecycle name collision: ctx.{c.name} already set",
                    )
                setattr(ctx, c.name, value)
            self._started.append(c)
            logger.info("Component %r started", c.name)

    async def stop(self) -> None:
        """Run ``stop()`` on every started component in **reverse** order."""
        while self._started:
            c = self._started.pop()
            try:
                await c.stop()
                logger.info("Component %r stopped", c.name)
            except Exception:
                logger.exception("Component %r stop() failed", c.name)
