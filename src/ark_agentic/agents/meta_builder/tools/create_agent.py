"""
create_agent Tool — 创建新 Agent 目录结构
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from ark_agentic.core.tools.base import AgentTool, ToolParameter
from ark_agentic.core.types import AgentToolResult, ToolCall
from ark_agentic.core.tools.base import read_string_param, read_list_param
from ark_agentic.core.utils.env import get_agents_root
from ark_agentic.studio.services.agent_service import AgentScaffoldSpec, scaffold_agent

logger = logging.getLogger(__name__)



class CreateAgentTool(AgentTool):
    """创建一个新的 Agent，包含目录结构、agent.json 和可选的初始 Skills。"""

    name = "create_agent"
    description = (
        "创建一个新 Agent 的完整目录结构（agent.json、skills/、tools/），"
        "并可以同时初始化 skills 列表。"
    )
    parameters = [
        ToolParameter(
            name="name",
            type="string",
            description="Agent 显示名称（中英文均可，会被自动 slugify 为目录名）",
            required=True,
        ),
        ToolParameter(
            name="description",
            type="string",
            description="Agent 的功能描述",
            required=False,
        ),
        ToolParameter(
            name="skills",
            type="array",
            description='初始技能列表，格式：[{"name": "...", "description": "...", "content": "..."}]',
            required=False,
        ),
    ]

    async def execute(self, tool_call: ToolCall, context: dict[str, Any] | None = None) -> AgentToolResult:
        args = tool_call.arguments
        name = read_string_param(args, "name", "")
        if not name:
            return AgentToolResult.error_result(tool_call.id, "参数 `name` 不能为空。")

        description = read_string_param(args, "description", "")
        skills_raw = read_list_param(args, "skills", [])

        spec = AgentScaffoldSpec(
            name=name,
            description=description or "",
            skills=[s for s in skills_raw if isinstance(s, dict)],
        )

        try:
            agent_dir = scaffold_agent(get_agents_root(__file__), spec)
            return AgentToolResult.error_result(tool_call.id, (
                    f"✅ Agent **{name}** 创建成功！\n"
                    f"- 目录: `{agent_dir}`\n"
                    f"- 初始技能数: {len(spec.skills)}\n"
                    f"刷新 Dashboard 即可看到新 Agent。"
                )
            )
        except FileExistsError as e:
            return AgentToolResult.text_result(tool_call.id, f"创建失败：{e}\n请换一个名称。")
        except ValueError as e:
            return AgentToolResult.error_result(tool_call.id, f"参数错误：{e}")
        except Exception as e:
            logger.exception("create_agent failed")
            return AgentToolResult.error_result(tool_call.id, f"创建 Agent 时发生错误：{e}")
