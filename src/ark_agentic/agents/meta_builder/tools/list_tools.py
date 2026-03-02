"""
list_tools Tool — 列出指定 Agent 的所有原生工具
"""

import logging
from typing import Any

from ark_agentic.core.tools.base import AgentTool, ToolParameter, read_string_param
from ark_agentic.core.types import AgentToolResult, ToolCall
from ark_agentic.core.utils.env import get_agents_root
from ark_agentic.studio.services.tool_service import list_tools as svc_list_tools

logger = logging.getLogger(__name__)

class ListToolsTool(AgentTool):
    """列出指定 Agent 下的所有原生 Tool。"""
    name = "list_tools"
    description = "列出目标 Agent 下已有的所有 Tools"
    parameters = [
        ToolParameter(name="agent_id", type="string", description="目标 Agent ID", required=False),
    ]

    async def execute(self, tool_call: ToolCall, context: dict[str, Any] | None = None) -> AgentToolResult:
        agent_id = read_string_param(tool_call.arguments, "agent_id", "")
        if not agent_id and context:
            agent_id = context.get("user:target_agent", "")
        if not agent_id:
            return AgentToolResult.error_result(tool_call.id, "需要指定 agent_id")

        try:
            tools = svc_list_tools(get_agents_root(__file__), agent_id)
            if not tools:
                return AgentToolResult.text_result(tool_call.id, f"Agent {agent_id} 还没有任何原生 Tool。")
            lines = [f"Agent {agent_id} 的原生工具列表:"]
            for t in tools:
                lines.append(f"- **{t.name}** ({t.file_path}): {t.description}")
            return AgentToolResult.text_result(tool_call.id, "\\n".join(lines))
        except Exception as e:
            return AgentToolResult.error_result(tool_call.id, f"列出工具失败: {e}")
