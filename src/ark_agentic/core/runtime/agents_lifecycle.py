"""AgentsLifecycle — core agents subsystem as a Lifecycle component.

Agents are a **core capability**, not a plugin: every ark-agentic
deployment needs them. The component nature is purely about lifecycle
orchestration — it lets Bootstrap drive agent registration, warmup and
shutdown alongside the rest of the application without app.py
hand-rolling those calls.

Phases:
  init    — no-op (agents have no schema; storage is per-agent dirs)
  start   — scan two roots and register every ``BaseAgent`` subclass:
              1. Framework-bundled ``ark_agentic/agents/``  — always
                 scanned, so the wheel's built-in ``meta_builder``
                 stays available to third-party deployments.
              2. User project's ``agents_root``             — resolved
                 by ``Bootstrap`` (explicit / env / convention).
            Then ``warmup()`` every registered agent and publish the
            registry as ``ctx.agent_registry``.
  stop    — ``close()`` every agent (release resources).

Discovery scans for ``BaseAgent`` subclasses (see
``core.runtime.discovery``) — no per-agent ``register()`` hook is
required, no ``register_all`` shim exists. Subclassing the base IS
the registration contract.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .base_agent import BaseAgent
from .discovery import discover_agents
from .registry import AgentRegistry
from ..protocol.lifecycle import BaseLifecycle

logger = logging.getLogger(__name__)

# Framework-bundled agents live next to this package: <ark_agentic>/agents
# Always scanned regardless of the user's agents_root, so wheel consumers
# get the built-in meta_builder agent automatically.
_FRAMEWORK_AGENTS_ROOT = Path(__file__).resolve().parent.parent.parent / "agents"


class AgentsLifecycle(BaseLifecycle):
    """Core agent registry orchestration."""

    name = "agent_registry"

    def __init__(
        self,
        registry: AgentRegistry | None = None,
        *,
        agents_root: Path | None = None,
    ) -> None:
        self._registry = registry or AgentRegistry()
        self._user_agents_root = agents_root

    @property
    def registry(self) -> AgentRegistry:
        """Read-only access for tests / external composition."""
        return self._registry

    async def start(self, ctx: Any) -> AgentRegistry:
        # Framework-bundled agents (always available)
        if _FRAMEWORK_AGENTS_ROOT.is_dir():
            discover_agents(self._registry, _FRAMEWORK_AGENTS_ROOT)

        # User project agents
        if self._user_agents_root is not None:
            discover_agents(self._registry, self._user_agents_root)
        else:
            logger.warning(
                "No user agents_root resolved; only framework-bundled "
                "agents loaded. Set AGENTS_ROOT or pass agents_root= to "
                "Bootstrap to enable user agent discovery."
            )

        for agent_id in self._registry.list_ids():
            agent: BaseAgent = self._registry.get(agent_id)
            await agent.warmup()
            logger.info("Agent '%s' warmed up", agent_id)

        logger.info("Agents started: %s", self._registry.list_ids())
        return self._registry

    async def stop(self) -> None:
        for agent_id in self._registry.list_ids():
            try:
                await self._registry.get(agent_id).close()
            except Exception:
                logger.exception("Agent '%s' close() failed", agent_id)
