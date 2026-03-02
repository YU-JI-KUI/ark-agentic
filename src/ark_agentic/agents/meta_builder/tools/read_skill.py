"""
read_skill Tool — 读取指定 Agent 的技能内容
"""

import logging
from typing import Any

from ark_agentic.core.tools.base import AgentTool, ToolParameter, read_string_param
from ark_agentic.core.types import AgentToolResult, ToolCall
from ark_agentic.core.utils.env import get_agents_root, resolve_agent_dir
from ark_agentic.studio.services.skill_service import parse_skill_dir 

logger = logging.getLogger(__name__)

class ReadSkillTool(AgentTool):
    """读取指定 Agent 下的一个 Skill 的详细内容。"""
    name = "read_skill"
    description = "根据 skill_id 读取技能的详细配置和内容 (SKILL.md)。"
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
            agents_root = get_agents_root(__file__)
            agent_dir = resolve_agent_dir(agents_root, agent_id)
            if not agent_dir:
                return AgentToolResult.error_result(tool_call.id, f"Agent {agent_id} 不存在。")
            
            skill_dir = agent_dir / "skills" / skill_id
            if not skill_dir.is_dir():
                return AgentToolResult.error_result(tool_call.id, f"Skill {skill_id} 不存在。")
                
            meta = parse_skill_dir(skill_dir)
            if not meta:
                return AgentToolResult.error_result(tool_call.id, "无法解析技能内容。")
                
            return AgentToolResult.text_result(tool_call.id, f"技能 {meta.name} 内容:\n`markdown\n{meta.content}\n`")
        except Exception as e:
            return AgentToolResult.error_result(tool_call.id, f"读取技能失败: {e}")
