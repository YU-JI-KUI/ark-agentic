"""APIPlugin shared FastAPI dependencies.

All consumers resolve the ``AgentRegistry`` from
``request.app.state.ctx.agent_registry`` (populated by
``Bootstrap.start`` from ``AgentsLifecycle``). No module-level
singleton; the request is the source of truth, so APIPlugin no longer
needs a separate ``start()`` step to copy the registry into a global.

Both ``get_registry`` and ``get_agent`` are usable as ``Depends(...)``
parameters **and** as plain function calls from inside a route body
that already holds a ``Request`` (e.g. ``chat.py``).
"""

from __future__ import annotations

from fastapi import HTTPException, Request

from ark_agentic.core.protocol.app_context import AppContext
from ark_agentic.core.runtime.registry import AgentRegistry
from ark_agentic.core.runtime.base_agent import BaseAgent


def _get_ctx(request: Request) -> AppContext:
    ctx = getattr(request.app.state, "ctx", None)
    if ctx is None:
        raise RuntimeError("AppContext is not initialised — did lifespan run?")
    return ctx


def get_registry(request: Request) -> AgentRegistry:
    """Resolve the ``AgentRegistry`` for this request."""
    ctx = _get_ctx(request)
    if ctx.agent_registry is None:
        raise RuntimeError(
            "AgentRegistry is not initialised — did Bootstrap.start run?",
        )
    return ctx.agent_registry


def get_agent(request: Request, agent_id: str) -> BaseAgent:
    """Look up a ``BaseAgent`` by id; 404 if not registered."""
    try:
        return get_registry(request).get(agent_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")
