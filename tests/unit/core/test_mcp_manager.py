from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from ark_agentic.core.mcp.config import MCPServerConfig, MCPToolPolicy
from ark_agentic.core.mcp.manager import MCPAgentRuntime, MCPManager
from ark_agentic.core.mcp.tool import MCPRemoteTool, MCPTool
from ark_agentic.core.runtime.registry import AgentRegistry
from ark_agentic.core.tools.registry import ToolRegistry


class FakeAgent:
    def __init__(self) -> None:
        self.tool_registry = ToolRegistry()


class FakeServer:
    def __init__(self, config: MCPServerConfig) -> None:
        self.config = config
        self.status = "connected"
        self.error = None
        self.tools = [
            MCPRemoteTool(
                name="search",
                description="Search",
                input_schema={"type": "object", "properties": {}},
            )
        ]
        self.closed = False

    def allowed_tools(self) -> list[MCPRemoteTool]:
        return [
            tool for tool in self.tools
            if self.config.tools.is_allowed(tool.name)
        ]

    async def close(self) -> None:
        self.closed = True


class RecordingServer(FakeServer):
    connect_tasks: list[asyncio.Task[object] | None] = []
    close_tasks: list[asyncio.Task[object] | None] = []

    async def connect(self) -> None:
        self.connect_tasks.append(asyncio.current_task())

    async def close(self) -> None:
        self.close_tasks.append(asyncio.current_task())
        await super().close()


@pytest.mark.asyncio
async def test_reload_agent_config_remounts_tools_without_closing_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "agent.json").write_text(
        json.dumps({
            "id": "sales",
            "mcp": {
                "servers": [
                    {
                        "id": "crm",
                        "transport": "stdio",
                        "command": "uvx",
                        "args": ["crm-server"],
                        "tools": {"enabled": {"search": False}},
                    }
                ]
            },
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "ark_agentic.core.mcp.manager._agent_dir",
        lambda _agent: tmp_path,
    )
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path / "config"))

    agent = FakeAgent()
    registry = AgentRegistry()
    registry.register("sales", agent)  # type: ignore[arg-type]
    manager = MCPManager()
    manager._registry = registry

    initial_config = MCPServerConfig(
        id="crm",
        name="CRM",
        description="",
        transport="stdio",
        command="uvx",
        args=["crm-server"],
        tools=MCPToolPolicy(enabled={"search": True}),
    )
    server = FakeServer(initial_config)
    runtime = MCPAgentRuntime(agent_id="sales", agent_dir=tmp_path)
    runtime.servers.append(server)  # type: ignore[arg-type]
    manager._agents["sales"] = runtime
    tool = MCPTool(
        server_id="crm",
        remote_tool=server.tools[0],
        session_provider=lambda _server_id: object(),
    )
    agent.tool_registry.register(tool)
    runtime.registered_tool_names.append(tool.name)

    await manager.reload_agent_config("sales")

    assert not server.closed
    assert not agent.tool_registry.has("mcp__crm__search")
    assert manager.snapshot("sales")[0]["enabled_tools"] == 0


@pytest.mark.asyncio
async def test_reload_agent_config_removes_deleted_server_without_closing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "agent.json").write_text(
        json.dumps({"id": "sales", "mcp": {"servers": []}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "ark_agentic.core.mcp.manager._agent_dir",
        lambda _agent: tmp_path,
    )
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path / "config"))

    agent = FakeAgent()
    registry = AgentRegistry()
    registry.register("sales", agent)  # type: ignore[arg-type]
    manager = MCPManager()
    manager._registry = registry

    initial_config = MCPServerConfig(
        id="crm",
        name="CRM",
        description="",
        transport="streamable_http",
        url="http://127.0.0.1:8000/mcp",
    )
    server = FakeServer(initial_config)
    runtime = MCPAgentRuntime(agent_id="sales", agent_dir=tmp_path)
    runtime.servers.append(server)  # type: ignore[arg-type]
    manager._agents["sales"] = runtime
    tool = MCPTool(
        server_id="crm",
        remote_tool=server.tools[0],
        session_provider=lambda _server_id: object(),
    )
    agent.tool_registry.register(tool)
    runtime.registered_tool_names.append(tool.name)

    await manager.reload_agent_config("sales")

    assert not server.closed
    assert manager._retired_streamable_servers == [server]
    assert not agent.tool_registry.has("mcp__crm__search")
    assert manager.snapshot("sales") == []


@pytest.mark.asyncio
async def test_reload_agent_config_retires_replaced_streamable_server(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "agent.json").write_text(
        json.dumps({
            "id": "sales",
            "mcp": {
                "servers": [
                    {
                        "id": "crm",
                        "transport": "streamable_http",
                        "url": "http://127.0.0.1:8001/mcp",
                    }
                ]
            },
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "ark_agentic.core.mcp.manager._agent_dir",
        lambda _agent: tmp_path,
    )
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setattr(
        "ark_agentic.core.mcp.manager.MCPServerRuntime",
        RecordingServer,
    )

    agent = FakeAgent()
    registry = AgentRegistry()
    registry.register("sales", agent)  # type: ignore[arg-type]
    manager = MCPManager()
    manager._registry = registry

    old_config = MCPServerConfig(
        id="crm",
        name="CRM",
        description="",
        transport="streamable_http",
        url="http://127.0.0.1:8000/mcp",
    )
    old_server = FakeServer(old_config)
    runtime = MCPAgentRuntime(agent_id="sales", agent_dir=tmp_path)
    runtime.servers.append(old_server)  # type: ignore[arg-type]
    manager._agents["sales"] = runtime

    await manager.reload_agent_config("sales")

    assert not old_server.closed
    assert manager._retired_streamable_servers == [old_server]
    assert manager.snapshot("sales")[0]["id"] == "crm"


@pytest.mark.asyncio
async def test_reload_agent_config_closes_removed_stdio_server(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "agent.json").write_text(
        json.dumps({"id": "sales", "mcp": {"servers": []}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "ark_agentic.core.mcp.manager._agent_dir",
        lambda _agent: tmp_path,
    )
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path / "config"))

    agent = FakeAgent()
    registry = AgentRegistry()
    registry.register("sales", agent)  # type: ignore[arg-type]
    manager = MCPManager()
    manager._registry = registry

    initial_config = MCPServerConfig(
        id="local",
        name="Local",
        description="",
        transport="stdio",
        command="uvx",
        args=["local-server"],
    )
    server = FakeServer(initial_config)
    runtime = MCPAgentRuntime(agent_id="sales", agent_dir=tmp_path)
    runtime.servers.append(server)  # type: ignore[arg-type]
    manager._agents["sales"] = runtime

    await manager.reload_agent_config("sales")

    assert server.closed
    assert manager._retired_streamable_servers == []
    assert manager.snapshot("sales") == []


@pytest.mark.asyncio
async def test_manager_worker_owns_connect_and_close(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "agent.json").write_text(
        json.dumps({
            "id": "sales",
            "mcp": {
                "servers": [
                    {
                        "id": "crm",
                        "transport": "stdio",
                        "command": "uvx",
                    }
                ]
            },
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "ark_agentic.core.mcp.manager._agent_dir",
        lambda _agent: tmp_path,
    )
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setattr(
        "ark_agentic.core.mcp.manager.MCPServerRuntime",
        RecordingServer,
    )
    RecordingServer.connect_tasks.clear()
    RecordingServer.close_tasks.clear()

    agent = FakeAgent()
    registry = AgentRegistry()
    registry.register("sales", agent)  # type: ignore[arg-type]
    manager = MCPManager()

    await manager.start(registry)
    await manager.refresh_agent("sales")
    await manager.close()

    assert RecordingServer.connect_tasks
    assert RecordingServer.close_tasks
    assert RecordingServer.connect_tasks[0] is RecordingServer.close_tasks[0]
