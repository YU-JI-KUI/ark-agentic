"""
update_tool Tool — 更新/覆写指定 Agent 的 Tool 源代码
"""

import logging
from typing import Any

from ark_agentic.core.tools.base import AgentTool, ToolParameter, read_string_param
from ark_agentic.core.types import AgentToolResult, ToolCall
from ark_agentic.core.utils.env import get_agents_root, resolve_agent_dir

logger = logging.getLogger(__name__)

class UpdateToolTool(AgentTool):
    """覆写/更新指定 Agent 下某个 Tool 的完整源代码。"""
    name = "update_tool"
    description = "覆写目标 Agent 下某个工具的 Python 源文件。"
    parameters = [
        ToolParameter(name="tool_name", type="string", description="工具模块的名称 (无.py后缀)", required=True),
        ToolParameter(name="content", type="string", description="完整的 Python 源码内容", required=True),
        ToolParameter(name="agent_id", type="string", description="目标 Agent ID", required=False),
    ]

    async def execute(self, tool_call: ToolCall, context: dict[str, Any] | None = None) -> AgentToolResult:
        tool_name = read_string_param(tool_call.arguments, "tool_name", "")
        content = read_string_param(tool_call.arguments, "content", "")
        agent_id = read_string_param(tool_call.arguments, "agent_id", "")
        if not agent_id and context:
            agent_id = context.get("user:target_agent", "")
        if not agent_id or not tool_name or not content:
            return AgentToolResult.error_result(tool_call.id, "需要指定 agent_id, tool_name, 以及 content")

        try:
            agents_root = get_agents_root(__file__)
            agent_dir = resolve_agent_dir(agents_root, agent_id)
            if not agent_dir:
                return AgentToolResult.error_result(tool_call.id, f"Agent {agent_id} 不存在。")
            
            tools_dir = agent_dir / "tools"
            if not tools_dir.is_dir():
                tools_dir.mkdir(parents=True)
                
            tool_file = tools_dir / f"{tool_name}.py"
            tool_file.write_text(content, encoding="utf-8")
            
            return AgentToolResult.text_result(tool_call.id, f"✅ 工具 {tool_name}.py 代码更新/生成成功！")
        except Exception as e:
            return AgentToolResult.error_result(tool_call.id, f"更新工具失败: {e}")
