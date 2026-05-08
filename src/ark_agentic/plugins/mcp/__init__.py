"""MCP client integration for ark-agentic."""

from .config import (
    MCPServerConfig,
    MCPToolPolicy,
    load_agent_mcp_config,
    load_agent_mcp_config_for_agent,
    mcp_registered_tool_name,
)
from .manager import MCPManager
from .plugin import MCPPlugin
from .tool import MCPRemoteTool, MCPTool

__all__ = [
    "MCPManager",
    "MCPRemoteTool",
    "MCPServerConfig",
    "MCPTool",
    "MCPToolPolicy",
    "load_agent_mcp_config",
    "load_agent_mcp_config_for_agent",
    "mcp_registered_tool_name",
    "MCPPlugin",
]
