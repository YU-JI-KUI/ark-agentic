"""
delete_tool Tool — 删除指定 Agent 的 Tool
"""

import logging
import os
from typing import Any

from ark_agentic.core.tools.base import AgentTool, ToolParameter, read_string_param
from ark_agentic.core.types import AgentToolResult, ToolCall
from ark_agentic.core.utils.env import get_agents_root, resolve_agent_dir

logger = logging.getLogger(__name__)

class DeleteToolTool(AgentTool):
    """删除指定 Agent 下的某个 Tool。"""
    name = "delete_tool"
    description = "删除目标 Agent 下的某个 Python 原生工具文件。"
    parameters = [
        ToolParameter(name="tool_name", type="string", description="工具模块的名称 (无.py后缀)", required=True),
        ToolParameter(name="agent_id", type="string", description="目标 Agent ID", required=False),
    ]

    async def execute(self, tool_call: ToolCall, context: dict[str, Any] | None = None) -> AgentToolResult:
        tool_name = read_string_param(tool_call.arguments, "tool_name", "")
        agent_id = read_string_param(tool_call.arguments, "agent_id", "")
        if not agent_id and context:
            agent_id = context.get("user:target_agent", "")
        if not agent_id or not tool_name:
            return AgentToolResult.error_result(tool_call.id, "需要指定 agent_id 和 tool_name")

        try:
            agents_root = get_agents_root(__file__)
            agent_dir = resolve_agent_dir(agents_root, agent_id)
            if not agent_dir:
                return AgentToolResult.error_result(tool_call.id, f"Agent {agent_id} 不存在。")
            
            tool_file = agent_dir / "tools" / f"{tool_name}.py"
            if not tool_file.is_file():
                return AgentToolResult.error_result(tool_call.id, f"Tool {tool_name}.py 不存在。")
                
            os.remove(tool_file)
            return AgentToolResult.text_result(tool_call.id, f"✅ 工具 {tool_name}.py 已删除。")
        except Exception as e:
            return AgentToolResult.error_result(tool_call.id, f"删除工具失败: {e}")
