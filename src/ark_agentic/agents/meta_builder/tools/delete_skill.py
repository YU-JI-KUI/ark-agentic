"""
delete_skill Tool — 删除指定 Agent 的技能
"""

import logging
from typing import Any

from ark_agentic.core.tools.base import AgentTool, ToolParameter, read_string_param
from ark_agentic.core.types import AgentToolResult, ToolCall
from ark_agentic.core.utils.env import get_agents_root
from ark_agentic.studio.services.skill_service import delete_skill as svc_delete_skill

logger = logging.getLogger(__name__)

class DeleteSkillTool(AgentTool):
    """删除指定 Agent 下的某个 Skill。"""
    name = "delete_skill"
    description = "谨慎操作！根据 skill_id 删除目标 Agent 下的某一个技能。"
    parameters = [
        ToolParameter(name="skill_id", type="string", description="技能的 ID（目录名）", required=True),
        ToolParameter(name="agent_id", type="string", description="目标 Agent ID", required=False),
    ]

    async def execute(self, tool_call: ToolCall, context: dict[str, Any] | None = None) -> AgentToolResult:
        skill_id = read_string_param(tool_call.arguments, "skill_id", "")
        agent_id = read_string_param(tool_call.arguments, "agent_id", "")
        if not agent_id and context:
            agent_id = context.get("user:target_agent", "")
        if not agent_id or not skill_id:
            return AgentToolResult.error_result(tool_call.id, "需要指定 agent_id 和 skill_id")

        try:
            svc_delete_skill(get_agents_root(__file__), agent_id, skill_id)
            return AgentToolResult.text_result(tool_call.id, f"✅ 技能 {skill_id} 删除成功。")
        except Exception as e:
            return AgentToolResult.error_result(tool_call.id, f"删除技能失败: {e}")
