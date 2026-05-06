"""AgentsLifecycle — core agents subsystem as a Lifecycle component.

Agents are a **core capability**, not a plugin: every ark-agentic
deployment needs them. The component nature is purely about lifecycle
orchestration — it lets Bootstrap drive agent registration and shutdown
alongside the rest of the application without app.py hand-rolling
those calls.

Phases:
  init    — no-op (agents have no schema; storage is per-agent dirs)
  start   — scan two roots and register every ``BaseAgent`` subclass:
              1. Framework-bundled ``ark_agentic/agents/``  — always
                 scanned, so the wheel's built-in ``meta_builder``
                 stays available to third-party deployments.
              2. User project's ``agents_root``             — resolved
                 by ``Bootstrap`` (explicit / env / convention).
            Publishes the registry as ``ctx.agent_registry``.
  stop    — ``close()`` every agent (release resources).

Discovery scans for ``BaseAgent`` subclasses (see
``core.runtime.discovery``) — no per-agent ``register()`` hook is
required, no ``register_all`` shim exists. Subclassing the base IS
the registration contract.

Per-agent startup tasks that depend on other plugins (e.g. proactive
job scheduling) are owned by those plugins and run in their own
``start()`` phase — agents themselves expose no warmup hook surface.
"""

from __future__ import annotations

import importlib.resources
import logging
from pathlib import Path
from typing import Any

from .discovery import discover_agents
from .registry import AgentRegistry
from ..protocol.lifecycle import BaseLifecycle

logger = logging.getLogger(__name__)


def _framework_agents_root() -> Path:
    """Return the framework-bundled ``ark_agentic/agents`` directory.

    Uses ``importlib.resources`` so the path tracks the installed package
    location regardless of where ``agents_lifecycle.py`` itself sits on
    disk — robust against future module reshuffles within ``core/``.
    """
    return Path(str(importlib.resources.files("ark_agentic"))) / "agents"


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
        framework_root = _framework_agents_root()
        if framework_root.is_dir():
            discover_agents(self._registry, framework_root)

        if self._user_agents_root is not None:
            discover_agents(self._registry, self._user_agents_root)
        else:
            logger.warning(
                "No user agents_root resolved; only framework-bundled "
                "agents loaded. Set AGENTS_ROOT or pass agents_root= to "
                "Bootstrap to enable user agent discovery."
            )

        logger.info("Agents started: %s", self._registry.list_ids())
        return self._registry

    async def stop(self) -> None:
        for agent_id in self._registry.list_ids():
            try:
                await self._registry.get(agent_id).close()
            except Exception:
                logger.exception("Agent '%s' close() failed", agent_id)
