from __future__ import annotations

import json
import sys
from contextlib import AsyncExitStack, asynccontextmanager
from types import ModuleType
from types import SimpleNamespace

import pytest

from ark_agentic.plugins.mcp.client import MCPServerRuntime
from ark_agentic.plugins.mcp.config import (
    MCPServerConfig,
    load_agent_mcp_config,
    load_agent_mcp_config_for_agent,
    mcp_registered_tool_name,
)
from ark_agentic.plugins.mcp.tool import MCPRemoteTool, MCPTool
from ark_agentic.core.types import ToolCall


class DifferentTaskCancelScopeStack:
    async def aclose(self) -> None:
        raise RuntimeError(
            "Attempted to exit cancel scope in a different task than it was "
            "entered in"
        )


class CurrentTaskCancelScopeStack:
    async def aclose(self) -> None:
        raise RuntimeError(
            "Attempted to exit a cancel scope that isn't the current tasks's "
            "current cancel scope"
        )


def test_load_agent_mcp_config_expands_env(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CRM_URL", "http://crm.example/mcp")
    monkeypatch.setenv("CRM_TOKEN", "secret")
    agent_json = {
        "id": "sales",
        "mcp": {
            "servers": [
                {
                    "id": "crm",
                    "name": "CRM",
                    "transport": "streamable_http",
                    "url": "${CRM_URL}",
                    "headers": {"Authorization": "Bearer ${CRM_TOKEN}"},
                    "tools": {
                        "allow": ["find_customer", "create_ticket"],
                        "deny": ["create_ticket"],
                        "enabled": {"find_customer": False},
                    },
                }
            ]
        },
    }
    (tmp_path / "agent.json").write_text(
        json.dumps(agent_json),
        encoding="utf-8",
    )

    [config] = load_agent_mcp_config(tmp_path)

    assert config.id == "crm"
    assert config.url == "http://crm.example/mcp"
    assert config.headers["Authorization"] == "Bearer secret"
    assert config.tools.is_allowed("find_customer")
    assert not config.tools.is_allowed("create_ticket")
    assert not config.tools.is_enabled("find_customer")
    assert config.tools.is_enabled("unknown_defaults_on")


def test_load_agent_mcp_config_splits_stdio_command_args(tmp_path) -> None:
    agent_json = {
        "id": "math",
        "mcp": {
            "servers": [
                {
                    "id": "math-server",
                    "transport": "stdio",
                    "command": "uv",
                    "args": [
                        "run --with mcp /tmp/math-server/math-server.py",
                    ],
                },
                {
                    "id": "quoted",
                    "transport": "stdio",
                    "command": "uv run --with mcp",
                    "args": [
                        "'/tmp/math server/math-server.py'",
                    ],
                },
            ],
        },
    }
    (tmp_path / "agent.json").write_text(
        json.dumps(agent_json),
        encoding="utf-8",
    )

    first, second = load_agent_mcp_config(tmp_path)

    assert first.command == "uv"
    assert first.args == [
        "run",
        "--with",
        "mcp",
        "/tmp/math-server/math-server.py",
    ]
    assert second.command == "uv"
    assert second.args == [
        "run",
        "--with",
        "mcp",
        "/tmp/math server/math-server.py",
    ]


def test_load_agent_mcp_config_prefers_config_dir(
    tmp_path,
    monkeypatch,
) -> None:
    legacy_dir = tmp_path / "agents" / "math"
    legacy_dir.mkdir(parents=True)
    (legacy_dir / "agent.json").write_text(
        json.dumps({
            "id": "math",
            "mcp": {
                "servers": [
                    {
                        "id": "legacy",
                        "transport": "stdio",
                        "command": "legacy-server",
                    }
                ]
            },
        }),
        encoding="utf-8",
    )
    config_dir = tmp_path / "config"
    monkeypatch.setenv("CONFIG_DIR", str(config_dir))
    (config_dir / "math").mkdir(parents=True)
    (config_dir / "math" / "agent.json").write_text(
        json.dumps({
            "id": "math",
            "mcp": {
                "servers": [
                    {
                        "id": "configured",
                        "transport": "stdio",
                        "command": "configured-server",
                    }
                ]
            },
        }),
        encoding="utf-8",
    )

    [config] = load_agent_mcp_config_for_agent(
        "math",
        legacy_agent_dir=legacy_dir,
    )

    assert config.id == "configured"
    assert config.command == "configured-server"


def test_mcp_registered_tool_name_is_stable() -> None:
    assert (
        mcp_registered_tool_name("lark", "bitable_v1_app_create")
        == "mcp__lark__bitable_v1_app_create"
    )


@pytest.mark.asyncio
async def test_streamable_http_uses_http_client_for_new_sdk_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}

    @asynccontextmanager
    async def streamable_http_client(
        url: str,
        *,
        http_client=None,
        terminate_on_close: bool = True,
    ):
        seen["url"] = url
        seen["authorization"] = http_client.headers.get("Authorization")
        seen["trust_env"] = http_client._trust_env
        yield "read", "write", lambda: None

    transport_module = ModuleType("mcp.client.streamable_http")
    transport_module.streamable_http_client = streamable_http_client
    client_module = ModuleType("mcp.client")
    client_module.streamable_http = transport_module
    mcp_module = ModuleType("mcp")

    monkeypatch.setitem(sys.modules, "mcp", mcp_module)
    monkeypatch.setitem(sys.modules, "mcp.client", client_module)
    monkeypatch.setitem(
        sys.modules,
        "mcp.client.streamable_http",
        transport_module,
    )

    runtime = MCPServerRuntime(
        MCPServerConfig(
            id="crm",
            name="CRM",
            description="",
            transport="streamable_http",
            url="http://localhost:8000/mcp",
            headers={"Authorization": "Bearer token"},
        )
    )

    stack = AsyncExitStack()
    try:
        read, write = await runtime._open_transport(stack)
    finally:
        await stack.aclose()

    assert (read, write) == ("read", "write")
    assert seen == {
        "url": "http://localhost:8000/mcp",
        "authorization": "Bearer token",
        "trust_env": False,
    }


@pytest.mark.asyncio
async def test_streamable_http_uses_legacy_headers_keyword(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}

    @asynccontextmanager
    async def streamable_http_client(url: str, *, headers=None):
        seen["url"] = url
        seen["headers"] = headers
        yield "read", "write"

    transport_module = ModuleType("mcp.client.streamable_http")
    transport_module.streamable_http_client = streamable_http_client
    client_module = ModuleType("mcp.client")
    client_module.streamable_http = transport_module
    mcp_module = ModuleType("mcp")

    monkeypatch.setitem(sys.modules, "mcp", mcp_module)
    monkeypatch.setitem(sys.modules, "mcp.client", client_module)
    monkeypatch.setitem(
        sys.modules,
        "mcp.client.streamable_http",
        transport_module,
    )

    runtime = MCPServerRuntime(
        MCPServerConfig(
            id="crm",
            name="CRM",
            description="",
            transport="streamable_http",
            url="http://localhost:8000/mcp",
            headers={"Authorization": "Bearer token"},
        )
    )

    stack = AsyncExitStack()
    try:
        read, write = await runtime._open_transport(stack)
    finally:
        await stack.aclose()

    assert (read, write) == ("read", "write")
    assert seen == {
        "url": "http://localhost:8000/mcp",
        "headers": {"Authorization": "Bearer token"},
    }


@pytest.mark.asyncio
async def test_runtime_close_suppresses_cross_task_cancel_error() -> None:
    runtime = MCPServerRuntime(
        MCPServerConfig(
            id="math",
            name="Math",
            description="",
            transport="streamable_http",
            url="http://127.0.0.1:8000/mcp",
        )
    )
    runtime._stack = (  # type: ignore[assignment]
        DifferentTaskCancelScopeStack()
    )
    runtime._session = object()
    runtime.status = "connected"

    await runtime.close()

    assert runtime.status == "closed"
    assert runtime._stack is None
    assert runtime._session is None


@pytest.mark.asyncio
async def test_runtime_close_suppresses_current_task_cancel_error() -> None:
    runtime = MCPServerRuntime(
        MCPServerConfig(
            id="math",
            name="Math",
            description="",
            transport="streamable_http",
            url="http://127.0.0.1:8000/mcp",
        )
    )
    runtime._stack = CurrentTaskCancelScopeStack()  # type: ignore[assignment]
    runtime._session = object()
    runtime.status = "connected"

    await runtime.close()

    assert runtime.status == "closed"
    assert runtime._stack is None
    assert runtime._session is None


@pytest.mark.asyncio
async def test_mcp_tool_returns_structured_content() -> None:
    class Session:
        async def call_tool(self, name, arguments):
            assert name == "search"
            assert arguments == {"q": "abc"}
            return SimpleNamespace(
                structuredContent={"items": [1, 2]},
                content=[],
                isError=False,
            )

    tool = MCPTool(
        server_id="crm",
        remote_tool=MCPRemoteTool(
            name="search",
            description="Search",
            input_schema={
                "type": "object",
                "properties": {"q": {"type": "string"}},
            },
        ),
        session_provider=lambda _server_id: Session(),
    )

    result = await tool.execute(ToolCall.create(tool.name, {"q": "abc"}))

    assert result.content == {"items": [1, 2]}
    assert result.metadata["source"] == "mcp"
    assert tool.get_json_schema()["function"]["name"] == "mcp__crm__search"


@pytest.mark.asyncio
async def test_mcp_tool_maps_mcp_error() -> None:
    class TextContent:
        text = "remote failed"

    class Session:
        async def call_tool(self, name, arguments):
            return SimpleNamespace(content=[TextContent()], isError=True)

    tool = MCPTool(
        server_id="crm",
        remote_tool=MCPRemoteTool(name="fail", description="Fail"),
        session_provider=lambda _server_id: Session(),
    )

    result = await tool.execute(ToolCall.create(tool.name, {}))

    assert result.is_error
    assert "remote failed" in str(result.content)
