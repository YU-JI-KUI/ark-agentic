"""AgentsRuntime — core agents subsystem as a Lifecycle component.

Agents are a **core capability**, not a plugin: every ark-agentic deployment
needs them. The component nature is purely about lifecycle orchestration —
it lets Bootstrap drive agent registration, warmup and shutdown alongside
the rest of the application without app.py hand-rolling those calls.

Phases:
  init    — no-op (agents have no schema; storage is per-agent dirs)
  start   — agents.register_all + per-runner warmup; publishes the
            registry as ``ctx.registry``; initialises the legacy
            ``api_deps.init_registry`` singleton for handlers that still
            pull the registry from there
  stop    — per-runner ``close_memory`` (release memory backends)
"""

from __future__ import annotations

import logging
import os
from typing import Any

from .registry import AgentRegistry
from ..protocol.lifecycle import BaseLifecycle

logger = logging.getLogger(__name__)


def _env_flag(name: str) -> bool:
    return os.getenv(name, "").lower() in ("true", "1")


def _enable_dream_default() -> bool:
    """Dream defaults to on unless ENABLE_DREAM is explicitly set false."""
    if "ENABLE_DREAM" in os.environ:
        return _env_flag("ENABLE_DREAM")
    return True


class AgentsRuntime(BaseLifecycle):
    """Core agent registry orchestration."""

    name = "registry"

    def __init__(self, registry: AgentRegistry | None = None) -> None:
        self._registry = registry or AgentRegistry()

    @property
    def registry(self) -> AgentRegistry:
        """Read-only access for tests / external composition."""
        return self._registry

    async def start(self, ctx: Any) -> AgentRegistry:
        from ...agents import register_all
        from ...plugins.api import deps as api_deps

        register_all(
            self._registry,
            enable_memory=_env_flag("ENABLE_MEMORY"),
            enable_dream=_enable_dream_default(),
        )
        # Legacy singleton: a few handlers still pull the registry via
        # api_deps. Keep it in sync until they switch to ctx.registry.
        api_deps.init_registry(self._registry)

        for agent_id in self._registry.list_ids():
            await self._registry.get(agent_id).warmup()
            logger.info("Agent '%s' warmed up", agent_id)

        logger.info("Agents started: %s", self._registry.list_ids())
        return self._registry

    async def stop(self) -> None:
        for agent_id in self._registry.list_ids():
            try:
                await self._registry.get(agent_id).close_memory()
            except Exception:
                logger.exception(
                    "Agent '%s' close_memory failed", agent_id,
                )
