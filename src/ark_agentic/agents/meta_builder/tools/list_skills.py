"""
list_skills Tool — 列出指定 Agent 的所有技能
"""

import logging
from typing import Any

from ark_agentic.core.tools.base import AgentTool, ToolParameter, read_string_param
from ark_agentic.core.types import AgentToolResult, ToolCall
from ark_agentic.core.utils.env import get_agents_root
from ark_agentic.studio.services.skill_service import list_skills as svc_list_skills

logger = logging.getLogger(__name__)

class ListSkillsTool(AgentTool):
    """列出指定 Agent 下的所有 Skill。"""
    name = "list_skills"
    description = "列出目标 Agent 下已有的所有 Skills。返回结果包含技能 ID、名称和描述。"
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
            skills = svc_list_skills(get_agents_root(__file__), agent_id)
            if not skills:
                return AgentToolResult.text_result(tool_call.id, f"Agent {agent_id} 还没有任何技能。")
            lines = [f"Agent {agent_id} 的技能列表:"]
            for s in skills:
                lines.append(f"- **{s.id}** ({s.name}): {s.description}")
            return AgentToolResult.text_result(tool_call.id, "\\n".join(lines))
        except Exception as e:
            return AgentToolResult.error_result(tool_call.id, f"列出技能失败: {e}")
