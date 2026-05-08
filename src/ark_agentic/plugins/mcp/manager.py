"""Runtime manager that mounts MCP tools onto discovered agents."""

from __future__ import annotations

import asyncio
import inspect
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, TypeVar

from ...core.runtime.base_agent import BaseAgent
from ...core.runtime.registry import AgentRegistry
from .client import MCPDependencyError, MCPServerRuntime
from .config import load_agent_mcp_config_for_agent, mcp_registered_tool_name
from .tool import MCPTool

logger = logging.getLogger(__name__)

T = TypeVar("T")


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
        self._retired_streamable_servers: list[MCPServerRuntime] = []
        self._op_queue: asyncio.Queue[
            tuple[Callable[[], Awaitable[Any]], asyncio.Future[Any]]
        ] | None = None
        self._worker_task: asyncio.Task[None] | None = None

    async def start(self, registry: AgentRegistry) -> None:
        self._registry = registry
        self._start_worker()
        for agent_id in registry.list_ids():
            await self.refresh_agent(agent_id)

    async def close(self) -> None:
        if self._worker_task is not None and (
            asyncio.current_task() is not self._worker_task
        ):
            try:
                await self._run_in_worker(self._close_inline)
            finally:
                await self._stop_worker()
            return
        await self._close_inline()

    async def refresh_agent(self, agent_id: str) -> None:
        """Re-read ``agent.json`` and remount MCP tools for one agent."""
        await self._run_in_worker(lambda: self._refresh_agent_inline(agent_id))

    async def _refresh_agent_inline(self, agent_id: str) -> None:
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
        """Re-read config and remount tools without closing unchanged sessions.

        Studio enable/disable mutations only affect exposure policy, so they
        reuse existing transports. Deleted or replaced streamable HTTP servers
        are retained instead of closed because the current MCP SDK can log
        async-generator cancel-scope errors when those transports are closed.
        """
        await self._run_in_worker(
            lambda: self._reload_agent_config_inline(agent_id)
        )

    async def _reload_agent_config_inline(self, agent_id: str) -> None:
        if self._registry is None:
            raise RuntimeError("MCPManager has not been started")
        agent = self._registry.get(agent_id)
        runtime = self._agents.get(agent_id)
        if runtime is None:
            await self._refresh_agent_inline(agent_id)
            return

        configs = load_agent_mcp_config_for_agent(
            agent_id,
            legacy_agent_dir=_agent_dir(agent),
        )
        servers_by_id = {
            server.config.id: server for server in runtime.servers
        }
        retired_servers: list[MCPServerRuntime] = []
        next_servers: list[MCPServerRuntime] = []
        for config in configs:
            server = servers_by_id.pop(config.id, None)
            if server is not None:
                if _same_connection_target(server.config, config):
                    server.config = config
                    next_servers.append(server)
                    continue
                retired_servers.append(server)

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

        retired_servers.extend(servers_by_id.values())
        for server in retired_servers:
            await self._retire_or_close_server(server)

        runtime.servers = next_servers
        self._remount_agent_tools(agent, runtime)

    async def _retire_or_close_server(
        self,
        server: MCPServerRuntime,
    ) -> None:
        if server.config.transport == "streamable_http":
            self._retired_streamable_servers.append(server)
            logger.debug(
                "Retired streamable HTTP MCP server %s without closing "
                "transport to avoid MCP SDK async-generator shutdown noise",
                server.config.id,
            )
            return
        await server.close()

    async def _close_inline(self) -> None:
        for agent_id in list(self._agents):
            await self._close_agent_runtime(agent_id)

    def _start_worker(self) -> None:
        if self._worker_task is not None:
            return
        self._op_queue = asyncio.Queue()
        self._worker_task = asyncio.create_task(
            self._worker_loop(),
            name="ark-mcp-manager",
        )

    async def _stop_worker(self) -> None:
        task = self._worker_task
        self._worker_task = None
        self._op_queue = None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _run_in_worker(
        self,
        operation: Callable[[], Awaitable[T]],
    ) -> T:
        if (
            self._worker_task is None
            or asyncio.current_task() is self._worker_task
        ):
            return await operation()
        if self._op_queue is None:
            raise RuntimeError("MCPManager worker is not initialised")
        loop = asyncio.get_running_loop()
        future: asyncio.Future[T] = loop.create_future()
        await self._op_queue.put((operation, future))
        return await future

    async def _worker_loop(self) -> None:
        if self._op_queue is None:
            return
        while True:
            operation, future = await self._op_queue.get()
            if future.cancelled():
                continue
            try:
                result = await operation()
            except Exception as exc:
                if not future.cancelled():
                    future.set_exception(exc)
            else:
                if not future.cancelled():
                    future.set_result(result)

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


def _same_connection_target(
    current: Any,
    next_config: Any,
) -> bool:
    if current.transport != next_config.transport:
        return False
    if current.transport == "streamable_http":
        return (
            current.url == next_config.url
            and current.headers == next_config.headers
        )
    return (
        current.command == next_config.command
        and current.args == next_config.args
        and current.env == next_config.env
    )


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
