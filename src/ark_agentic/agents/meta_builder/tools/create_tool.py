"""
create_tool Tool — 为指定 Agent 生成 AgentTool Python 脚手架
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from ark_agentic.core.tools.base import AgentTool, ToolParameter, read_string_param, read_list_param
from ark_agentic.core.types import AgentToolResult, ToolCall
from ark_agentic.core.utils.env import get_agents_root
from ark_agentic.studio.services.tool_service import scaffold_tool as svc_scaffold_tool, ToolParameterSpec

logger = logging.getLogger(__name__)



class CreateToolTool(AgentTool):
    """为指定 Agent 生成一个 AgentTool Python 脚手架文件（tools/{name}.py）。"""

    name = "create_tool"
    description = (
        "在指定 Agent 的 tools/ 目录下生成 Python 工具脚手架文件，"
        "包含正确的类结构和参数 Schema，开发者只需填写 execute() 逻辑。"
    )
    parameters = [
        ToolParameter(
            name="name",
            type="string",
            description="工具名称（必须是合法的 Python snake_case 标识符，如 check_policy）",
            required=True,
        ),
        ToolParameter(
            name="description",
            type="string",
            description="工具的功能描述",
            required=False,
        ),
        ToolParameter(
            name="parameters",
            type="array",
            description='工具参数定义列表，格式：[{"name":"...", "description":"...", "type":"string", "required":true}]',
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

        agent_id = read_string_param(args, "agent_id", "")
        if not agent_id and context:
            agent_id = context.get("user:target_agent", "")
        if not agent_id:
            return AgentToolResult.text_result(tool_call.id, "需要指定 `agent_id`，或在当前 Agent 管理页打开 Meta-Agent 对话。",
                is_error=True,
            )

        description = read_string_param(args, "description", "")
        params_raw = read_list_param(args, "parameters", [])
        params = [ToolParameterSpec(**p) for p in params_raw if isinstance(p, dict)]

        try:
            meta = svc_scaffold_tool(
                agents_root=get_agents_root(__file__),
                agent_id=agent_id,
                name=name,
                description=description,
                parameters=params,
            )
            return AgentToolResult.text_result(tool_call.id, (
                    f"✅ Tool **{meta.name}** 脚手架生成成功！\n"
                    f"- Agent: `{agent_id}`\n"
                    f"- 文件: `{meta.file_path}`\n"
                    f"请打开文件，在 `execute()` 方法中实现具体逻辑。"
                )
            )
        except ValueError as e:
            return AgentToolResult.text_result(tool_call.id, f"参数错误：{e}")
        except FileNotFoundError as e:
            return AgentToolResult.error_result(tool_call.id, f"Agent 不存在：{e}")
        except FileExistsError as e:
            return AgentToolResult.error_result(tool_call.id, f"同名工具文件已存在：{e}")
        except Exception as e:
            logger.exception("create_tool failed")
            return AgentToolResult.error_result(tool_call.id, f"生成工具脚手架时发生错误：{e}")
