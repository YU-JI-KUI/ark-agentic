"""
update_skill Tool — 更新指定 Agent 的现有技能
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from ark_agentic.core.tools.base import AgentTool, ToolParameter, read_string_param
from ark_agentic.core.types import AgentToolResult, ToolCall
from ark_agentic.core.utils.env import get_agents_root
from ark_agentic.studio.services.skill_service import update_skill as svc_update_skill

logger = logging.getLogger(__name__)



class UpdateSkillTool(AgentTool):
    """更新指定 Agent 下已有 Skill 的内容或描述。"""

    name = "update_skill"
    description = (
        "更新指定 Agent 下已有的 Skill 内容（SKILL.md）。"
        "agent_id 和 skill_id 默认从对话上下文获取。"
    )
    parameters = [
        ToolParameter(
            name="skill_id",
            type="string",
            description="技能 ID（通常是技能目录名，如 claim-rejection）",
            required=True,
        ),
        ToolParameter(
            name="content",
            type="string",
            description="新的 SKILL.md 正文内容（Markdown 格式）",
            required=False,
        ),
        ToolParameter(
            name="description",
            type="string",
            description="更新技能简短描述",
            required=False,
        ),
        ToolParameter(
            name="name",
            type="string",
            description="重命名技能（更新 frontmatter 中的 name）",
            required=False,
        ),
        ToolParameter(
            name="agent_id",
            type="string",
            description="目标 Agent ID，不填则使用当前对话上下文中的 target_agent",
            required=False,
        ),
    ]

    async def execute(self, tool_call: ToolCall, context: dict[str, Any] | None = None) -> AgentToolResult:
        args = tool_call.arguments
        skill_id = read_string_param(args, "skill_id", "")
        if not skill_id:
            return AgentToolResult.error_result(tool_call.id, "参数 `skill_id` 不能为空。")

        agent_id = read_string_param(args, "agent_id", "")
        if not agent_id and context:
            agent_id = context.get("user:target_agent", "")
        if not agent_id:
            return AgentToolResult.text_result(tool_call.id, "需要指定 `agent_id`，或在当前 Agent 管理页打开 Meta-Agent 对话。",
                is_error=True,
            )

        name = read_string_param(args, "name", None)
        description = read_string_param(args, "description", None)
        content = read_string_param(args, "content", None)

        if not any([name, description, content]):
            return AgentToolResult.error_result(tool_call.id, "请至少指定一个要更新的字段（name/description/content）。")

        try:
            meta = svc_update_skill(
                agents_root=get_agents_root(__file__),
                agent_id=agent_id,
                skill_id=skill_id,
                name=name,
                description=description,
                content=content,
            )
            return AgentToolResult.text_result(tool_call.id, (
                    f"✅ Skill **{meta.name}** 更新成功！\n"
                    f"- Agent: `{agent_id}`\n"
                    f"- 文件: `{meta.file_path}`"
                )
            )
        except FileNotFoundError as e:
            return AgentToolResult.text_result(tool_call.id, f"技能不存在：{e}")
        except Exception as e:
            logger.exception("update_skill failed")
            return AgentToolResult.error_result(tool_call.id, f"更新技能时发生错误：{e}")
