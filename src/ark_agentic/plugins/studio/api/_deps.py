"""StudioPlugin internal FastAPI dependencies.

Studio resolves the ``AgentRegistry`` from ``request.app.state.ctx``
directly (set by ``Bootstrap.start`` from
``AppContext.agent_registry``) so it does not import APIPlugin's deps
module — Studio works whether or not ``ENABLE_API`` is set.
"""

from __future__ import annotations

from fastapi import HTTPException, Request

from ark_agentic.core.protocol.app_context import AppContext
from ark_agentic.core.runtime.registry import AgentRegistry


def _get_ctx(request: Request) -> AppContext:
    ctx = getattr(request.app.state, "ctx", None)
    if ctx is None:
        raise RuntimeError("AppContext is not initialised — did lifespan run?")
    return ctx


def get_registry(request: Request) -> AgentRegistry:
    """Resolve the ``AgentRegistry`` for this request."""
    ctx = _get_ctx(request)
    if ctx.agent_registry is None:
        raise HTTPException(
            status_code=503, detail="AgentRegistry is not initialised",
        )
    return ctx.agent_registry
