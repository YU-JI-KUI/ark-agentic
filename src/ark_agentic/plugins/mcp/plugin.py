"""MCPPlugin — mounts external MCP tools onto agents."""

from __future__ import annotations

from typing import Any

from .manager import MCPManager
from ...core.protocol.plugin import BasePlugin
from ...core.utils.env import env_flag


class MCPPlugin(BasePlugin):
    """Optional MCP client integration, disabled by default."""

    name = "mcp"

    def __init__(self) -> None:
        self._manager: MCPManager | None = None

    def is_enabled(self) -> bool:
        return env_flag("ENABLE_MCP", default=False)

    async def start(self, ctx: Any) -> MCPManager:
        if getattr(ctx, "agent_registry", None) is None:
            raise RuntimeError(
                "MCPPlugin requires agent_registry to be started first"
            )
        manager = MCPManager()
        await manager.start(ctx.agent_registry)
        self._manager = manager
        return manager

    async def stop(self) -> None:
        if self._manager is not None:
            await self._manager.close()
            self._manager = None
