"""AgentsLifecycle — core agents subsystem as a Lifecycle component.

Agents are a **core capability**, not a plugin: every ark-agentic deployment
needs them. The component nature is purely about lifecycle orchestration —
it lets Bootstrap drive agent registration, warmup and shutdown alongside
the rest of the application without app.py hand-rolling those calls.

Phases:
  init    — no-op (agents have no schema; storage is per-agent dirs)
  start   — filesystem-rooted agent discovery via ``AGENTS_ROOT`` (or
            its auto-detect fallback) + per-runner warmup; publishes
            the registry as ``ctx.agent_registry``. Plugins that need
            the registry read it from there.
  stop    — per-runner ``close_memory`` (release memory backends)

Discovery is filesystem-driven (see ``core.runtime.discovery``) so core
holds zero knowledge of any specific agents package — wheel consumers'
``src/<their_pkg>/agents`` is picked up the same way as the framework's
own ``src/ark_agentic/agents``.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from .discovery import discover_and_register_agents
from .registry import AgentRegistry
from ..protocol.lifecycle import BaseLifecycle
from ..utils.env import env_flag, get_agents_root

logger = logging.getLogger(__name__)


def _enable_dream_default() -> bool:
    """Dream defaults to on unless ENABLE_DREAM is explicitly set false."""
    if "ENABLE_DREAM" in os.environ:
        return env_flag("ENABLE_DREAM")
    return True


class AgentsLifecycle(BaseLifecycle):
    """Core agent registry orchestration."""

    name = "agent_registry"

    def __init__(self, registry: AgentRegistry | None = None) -> None:
        self._registry = registry or AgentRegistry()

    @property
    def registry(self) -> AgentRegistry:
        """Read-only access for tests / external composition."""
        return self._registry

    async def start(self, ctx: Any) -> AgentRegistry:
        agents_root = get_agents_root(__file__)
        discover_and_register_agents(
            self._registry,
            agents_root,
            enable_memory=env_flag("ENABLE_MEMORY"),
            enable_dream=_enable_dream_default(),
        )

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
