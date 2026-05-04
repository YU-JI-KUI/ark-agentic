"""Plugin Protocol — uniform contract for built-in & third-party plugins.

A Plugin packages an optional feature with four lifecycle hooks; the host
(``app.py`` for the FastAPI deployment, CLI scaffolds for generated
projects) drives every Plugin through the same flow:

    for p in PLUGINS:
        if not p.is_enabled():
            continue
        await p.init_schema()
        p.install_routes(app)
    async with AsyncExitStack() as stack:
        for p in PLUGINS:
            if not p.is_enabled():
                continue
            value = await stack.enter_async_context(p.lifespan(app_ctx))
            setattr(app_ctx, p.name, value)
        yield  # serving

Different plugins use different subsets of the lifecycle:
- HTTP feature: ``install_routes`` + ``lifespan``
- Pure background worker: ``lifespan`` only
- Schema-only contributor: ``init_schema`` only

``BasePlugin`` provides no-op defaults so each Plugin class only overrides
the hooks it actually uses.

Future-compat: when (and only when) the project gains real third-party
plugins, the same Protocol can be loaded via ``importlib.metadata``
``entry_points`` without changing this file. Today's built-in plugins
are statically registered in a ``PLUGINS`` list — no discovery, no
isolation, no hidden cost.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Protocol, runtime_checkable

# ``FastAPI`` is annotated as Any here so ``core/`` does not import the
# fastapi package — the Plugin Protocol stays HTTP-agnostic in case future
# transports (CLI worker, gRPC) want to reuse it. Concrete plugins under
# ``services/*`` / ``plugins/*`` annotate their own signatures with the
# real ``FastAPI`` type.


@runtime_checkable
class Plugin(Protocol):
    """A pluggable feature unit registered statically in the host app's
    PLUGINS list. Each plugin contributes some combination of (schema,
    routes, runtime context, background tasks)."""

    name: str
    """Identifier used as the ``AppContext`` field name and in logs."""

    def is_enabled(self) -> bool:
        """Env-driven on/off gate. Disabled plugins are skipped entirely."""
        ...

    async def init_schema(self) -> None:
        """Create owned persistent storage. Idempotent. No-op when not needed."""
        ...

    def install_routes(self, app: Any) -> None:
        """Mount HTTP routers on the given FastAPI app (module-load time)."""
        ...

    @asynccontextmanager
    async def lifespan(self, app_ctx: Any) -> AsyncIterator[Any]:
        """Build runtime context, start background tasks, yield the value
        the host should attach to ``AppContext.{name}``, clean up on shutdown.

        May read other plugins' fields from ``app_ctx`` provided they were
        registered earlier in the PLUGINS list."""
        ...


class BasePlugin:
    """Default no-op implementation. Concrete plugins override only the
    hooks they actually use.

    Subclasses MUST set ``name``. Everything else is opt-in."""

    name: str = ""

    def is_enabled(self) -> bool:
        return True

    async def init_schema(self) -> None:
        return None

    def install_routes(self, app: Any) -> None:
        return None

    @asynccontextmanager
    async def lifespan(self, app_ctx: Any) -> AsyncIterator[Any]:
        yield None
