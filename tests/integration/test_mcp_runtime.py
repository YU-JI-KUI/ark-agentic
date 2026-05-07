from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from ark_agentic.core.mcp.client import MCPServerRuntime
from ark_agentic.core.mcp.config import MCPServerConfig
from ark_agentic.core.mcp.tool import MCPTool
from ark_agentic.core.types import ToolCall


pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("mcp") is None,
    reason="mcp optional dependency is not installed",
)


@pytest.mark.asyncio
async def test_mcp_runtime_connects_to_repo_math_server() -> None:
    server_path = Path("tests/mcp/math-server.py").resolve()
    runtime = MCPServerRuntime(
        MCPServerConfig(
            id="math-server",
            name="MathServer",
            description="Math MCP test server",
            transport="stdio",
            command=sys.executable,
            args=[str(server_path)],
        )
    )

    await runtime.connect()
    try:
        tool_names = {tool.name for tool in runtime.allowed_tools()}
        assert tool_names == {"add", "multiply"}

        add_tool = next(
            tool for tool in runtime.allowed_tools()
            if tool.name == "add"
        )
        wrapped = MCPTool(
            server_id="math-server",
            remote_tool=add_tool,
            session_provider=lambda _server_id: runtime.get_session(),
        )
        result = await wrapped.execute(
            ToolCall.create(wrapped.name, {"a": 2, "b": 3})
        )

        assert not result.is_error
        assert "5" in str(result.content)
    finally:
        await runtime.close()
