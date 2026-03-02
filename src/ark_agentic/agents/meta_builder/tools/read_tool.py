"""
read_tool Tool — 读取指定 Agent 的 Tool 源代码
"""

import logging
from typing import Any

from ark_agentic.core.tools.base import AgentTool, ToolParameter, read_string_param
from ark_agentic.core.types import AgentToolResult, ToolCall
from ark_agentic.core.utils.env import get_agents_root, resolve_agent_dir

logger = logging.getLogger(__name__)

class ReadToolTool(AgentTool):
    """读取指定 Agent 下的某个 Tool 源文件。"""
    name = "read_tool"
    description = "读取目标 Agent 下某个工具的 Python 源文件。"
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
                
            content = tool_file.read_text(encoding="utf-8")
            return AgentToolResult.text_result(tool_call.id, f"工具 {tool_name}.py 源码:\n`python\n{content}\n`")
        except Exception as e:
            return AgentToolResult.error_result(tool_call.id, f"读取工具失败: {e}")
