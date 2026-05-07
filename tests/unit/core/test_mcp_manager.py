from __future__ import annotations

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
