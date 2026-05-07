"""Runtime manager that mounts MCP tools onto discovered agents."""

from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..runtime.base_agent import BaseAgent
from ..runtime.registry import AgentRegistry
from .client import MCPDependencyError, MCPServerRuntime
from .config import load_agent_mcp_config_for_agent, mcp_registered_tool_name
from .tool import MCPTool

logger = logging.getLogger(__name__)


@dataclass
class MCPAgentRuntime:
    agent_id: str
    agent_dir: Path
    servers: list[MCPServerRuntime] = field(default_factory=list)
    registered_tool_names: list[str] = field(default_factory=list)


class MCPManager:
    """Owns MCP sessions and dynamically registered MCP tools."""

    def __init__(self) -> None:
        self._registry: AgentRegistry | None = None
        self._agents: dict[str, MCPAgentRuntime] = {}

    async def start(self, registry: AgentRegistry) -> None:
        self._registry = registry
        for agent_id in registry.list_ids():
            await self.refresh_agent(agent_id)

    async def close(self) -> None:
        for agent_id in list(self._agents):
            await self._close_agent_runtime(agent_id)

    async def refresh_agent(self, agent_id: str) -> None:
        """Re-read ``agent.json`` and remount MCP tools for one agent."""
        if self._registry is None:
            raise RuntimeError("MCPManager has not been started")
        agent = self._registry.get(agent_id)
        await self._close_agent_runtime(agent_id)

        agent_dir = _agent_dir(agent)
        configs = load_agent_mcp_config_for_agent(
            agent_id,
            legacy_agent_dir=agent_dir,
        )
        runtime = MCPAgentRuntime(agent_id=agent_id, agent_dir=agent_dir)
        self._agents[agent_id] = runtime
        if not configs:
            return

        for config in configs:
            server = MCPServerRuntime(config)
            runtime.servers.append(server)
            try:
                await server.connect()
            except MCPDependencyError:
                if config.required:
                    raise
                logger.warning(
                    "MCP dependency unavailable for optional server %s/%s",
                    agent_id,
                    config.id,
                )
                continue
            except Exception as exc:
                if config.required:
                    raise RuntimeError(
                        f"Required MCP server '{config.id}' failed: {exc}"
                    ) from exc
                logger.warning(
                    "Optional MCP server %s/%s failed: %s",
                    agent_id,
                    config.id,
                    exc,
                )
                continue

        self._remount_agent_tools(agent, runtime)

    async def reload_agent_config(self, agent_id: str) -> None:
        """Re-read config and remount MCP tools without closing sessions.

        Studio enable/disable mutations only affect exposure policy, so they
        must not tear down stdio transports opened by the startup task.
        """
        if self._registry is None:
            raise RuntimeError("MCPManager has not been started")
        agent = self._registry.get(agent_id)
        runtime = self._agents.get(agent_id)
        if runtime is None:
            await self.refresh_agent(agent_id)
            return

        configs = load_agent_mcp_config_for_agent(
            agent_id,
            legacy_agent_dir=_agent_dir(agent),
        )
        servers_by_id = {
            server.config.id: server for server in runtime.servers
        }
        next_servers: list[MCPServerRuntime] = []
        for config in configs:
            server = servers_by_id.get(config.id)
            if server is not None:
                server.config = config
                next_servers.append(server)
                continue

            server = MCPServerRuntime(config)
            next_servers.append(server)
            try:
                await server.connect()
            except MCPDependencyError:
                if config.required:
                    raise
                logger.warning(
                    "MCP dependency unavailable for optional server %s/%s",
                    agent_id,
                    config.id,
                )
            except Exception as exc:
                if config.required:
                    raise RuntimeError(
                        f"Required MCP server '{config.id}' failed: {exc}"
                    ) from exc
                logger.warning(
                    "Optional MCP server %s/%s failed: %s",
                    agent_id,
                    config.id,
                    exc,
                )

        runtime.servers = next_servers
        self._remount_agent_tools(agent, runtime)

    def get_session(self, agent_id: str, server_id: str) -> Any:
        runtime = self._agents.get(agent_id)
        if runtime is None:
            raise RuntimeError(f"No MCP runtime for agent '{agent_id}'")
        for server in runtime.servers:
            if server.config.id == server_id:
                return server.get_session()
        raise RuntimeError(
            f"MCP server '{server_id}' not found for agent '{agent_id}'"
        )

    def snapshot(self, agent_id: str) -> list[dict[str, Any]]:
        runtime = self._agents.get(agent_id)
        if runtime is None:
            return []
        return [_server_snapshot(server) for server in runtime.servers]

    async def _close_agent_runtime(self, agent_id: str) -> None:
        runtime = self._agents.pop(agent_id, None)
        if runtime is None:
            return
        if self._registry is not None:
            try:
                agent = self._registry.get(agent_id)
            except KeyError:
                agent = None
            if agent is not None:
                for name in runtime.registered_tool_names:
                    agent.tool_registry.unregister(name)
        for server in runtime.servers:
            await server.close()

    def _remount_agent_tools(
        self,
        agent: BaseAgent,
        runtime: MCPAgentRuntime,
    ) -> None:
        for name in runtime.registered_tool_names:
            agent.tool_registry.unregister(name)
        runtime.registered_tool_names.clear()

        for server in runtime.servers:
            config = server.config
            if not config.enabled or server.status != "connected":
                continue
            for remote_tool in server.allowed_tools():
                if not config.tools.is_enabled(remote_tool.name):
                    continue
                tool = MCPTool(
                    server_id=config.id,
                    remote_tool=remote_tool,
                    session_provider=lambda sid, aid=runtime.agent_id: (
                        self.get_session(aid, sid)
                    ),
                    timeout=config.timeout,
                )
                agent.tool_registry.register(tool)
                runtime.registered_tool_names.append(tool.name)


def _agent_dir(agent: BaseAgent) -> Path:
    try:
        return Path(inspect.getfile(type(agent))).resolve().parent
    except TypeError:
        return Path.cwd()


def _server_snapshot(server: MCPServerRuntime) -> dict[str, Any]:
    cfg = server.config
    tools: list[dict[str, Any]] = []
    for tool in server.allowed_tools():
        method_enabled = cfg.tools.is_enabled(tool.name)
        tools.append({
            "name": tool.name,
            "registered_name": mcp_registered_tool_name(cfg.id, tool.name),
            "description": tool.description,
            "enabled": method_enabled,
            "input_schema": tool.input_schema,
            "parameter_count": len(
                (tool.input_schema or {}).get("properties") or {}
            ),
        })
    enabled_count = (
        sum(1 for tool in tools if tool["enabled"])
        if cfg.enabled else 0
    )
    return {
        "id": cfg.id,
        "name": cfg.name,
        "description": cfg.description,
        "transport": cfg.transport,
        "enabled": cfg.enabled,
        "required": cfg.required,
        "status": server.status if cfg.enabled else "disabled",
        "error": server.error,
        "total_tools": len(tools),
        "enabled_tools": enabled_count,
        "tools": tools,
    }
