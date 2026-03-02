"""
create_skill Tool — 为指定 Agent 创建新技能
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from ark_agentic.core.tools.base import AgentTool, ToolParameter, read_string_param
from ark_agentic.core.types import AgentToolResult, ToolCall
from ark_agentic.core.utils.env import get_agents_root
from ark_agentic.studio.services.skill_service import create_skill as svc_create_skill

logger = logging.getLogger(__name__)



class CreateSkillTool(AgentTool):
    """为指定 Agent 创建新的 Skill（生成 SKILL.md 目录和文件）。"""

    name = "create_skill"
    description = (
        "在指定 Agent 下创建一个新 Skill，生成 skills/{skill_name}/SKILL.md 文件。"
        "agent_id 默认从当前操作上下文（user:target_agent）获取。"
    )
    parameters = [
        ToolParameter(
            name="name",
            type="string",
            description="技能名称（中英文均可）",
            required=True,
        ),
        ToolParameter(
            name="description",
            type="string",
            description="技能的简短描述",
            required=False,
        ),
        ToolParameter(
            name="content",
            type="string",
            description="SKILL.md 正文内容（Markdown 格式的业务规范文档，内容越丰富越好）",
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
        name = read_string_param(args, "name", "")
        if not name:
            return AgentToolResult.error_result(tool_call.id, "参数 `name` 不能为空。")

        # 优先取参数中的 agent_id，其次从 context 获取 target_agent
        agent_id = read_string_param(args, "agent_id", "")
        if not agent_id and context:
            agent_id = context.get("user:target_agent", "")
        if not agent_id:
            return AgentToolResult.text_result(tool_call.id, "需要指定 `agent_id`，或在当前 Agent 管理页打开 Meta-Agent 对话。",
                is_error=True,
            )

        description = read_string_param(args, "description", "")
        content = read_string_param(args, "content", "")

        try:
            meta = svc_create_skill(
                agents_root=get_agents_root(__file__),
                agent_id=agent_id,
                name=name,
                description=description,
                content=content,
            )
            return AgentToolResult.text_result(tool_call.id, (
                    f"✅ Skill **{meta.name}** 创建成功！\n"
                    f"- Agent: `{agent_id}`\n"
                    f"- 文件: `{meta.file_path}`\n"
                    f"刷新 Skills 面板即可看到新技能。"
                )
            )
        except FileNotFoundError as e:
            return AgentToolResult.text_result(tool_call.id, f"Agent 不存在：{e}")
        except FileExistsError as e:
            return AgentToolResult.error_result(tool_call.id, f"同名技能已存在：{e}")
        except ValueError as e:
            return AgentToolResult.error_result(tool_call.id, f"参数错误：{e}")
        except Exception as e:
            logger.exception("create_skill failed")
            return AgentToolResult.error_result(tool_call.id, f"创建技能时发生错误：{e}")
