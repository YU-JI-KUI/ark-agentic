"""
manage_tools — 复合工具：Tool 的 list / create / update / delete / read

create/update/delete 必须先让用户回复「我确认变更」后，再次调用并传入 confirmation='我确认变更'。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from ark_agentic.core.tools.base import AgentTool, ToolParameter, read_string_param, read_list_param
from ark_agentic.core.types import AgentToolResult, ToolCall
from ark_agentic.core.utils.env import get_agents_root, resolve_agent_dir
from ark_agentic.studio.services.tool_service import (
    list_tools as svc_list_tools,
    scaffold_tool as svc_scaffold_tool,
    ToolParameterSpec,
)

logger = logging.getLogger(__name__)

CONFIRMATION_PHRASE = "我确认变更"
_ACTIONS = ["list", "create", "update", "delete", "read"]


def _err(tool_call_id: str, msg: str) -> AgentToolResult:
    return AgentToolResult.error_result(tool_call_id, msg)


def _ok(tool_call_id: str, msg: str) -> AgentToolResult:
    return AgentToolResult.text_result(tool_call_id, msg)


def _require_confirmation(
    confirmation: str | None, tool_call_id: str, action_desc: str
) -> AgentToolResult | None:
    if (confirmation or "").strip() != CONFIRMATION_PHRASE:
        return _err(
            tool_call_id,
            f"增删改操作必须先让用户回复「{CONFIRMATION_PHRASE}」后，再次调用本工具并传入 confirmation='{CONFIRMATION_PHRASE}' 以执行。本次拟执行：{action_desc}",
        )
    return None


def _resolve_agent_id(args: dict, context: dict[str, Any] | None) -> str | None:
    aid = read_string_param(args, "agent_id", "") or ""
    if aid:
        return aid
    if context:
        return (context.get("user:target_agent") or "").strip() or None
    return None


def _validate_tool_name(tool_name: str, tool_call_id: str) -> AgentToolResult | None:
    if not tool_name or not tool_name.strip():
        return _err(tool_call_id, "tool_name 不能为空。")
    if not tool_name.strip().isidentifier():
        return _err(tool_call_id, "tool_name 必须为合法 Python 标识符（如 check_policy）。")
    return None


async def _do_list_tools(
    agents_root: Path, tool_call_id: str, agent_id: str
) -> AgentToolResult:
    try:
        tools = svc_list_tools(agents_root, agent_id)
    except FileNotFoundError:
        return _err(tool_call_id, "Agent 不存在。")
    except Exception as e:
        logger.exception("list_tools failed")
        return _err(tool_call_id, f"列出工具失败：{e}")
    if not tools:
        return _ok(tool_call_id, f"Agent {agent_id} 还没有任何原生 Tool。")
    lines = [f"Agent {agent_id} 的原生工具列表:"]
    for t in tools:
        lines.append(f"- **{t.name}** ({t.file_path}): {t.description or ''}")
    return _ok(tool_call_id, "\n".join(lines))


async def _do_create_tool(
    agents_root: Path,
    tool_call_id: str,
    agent_id: str,
    name: str,
    description: str,
    parameters: list,
) -> AgentToolResult:
    if not name.strip().isidentifier():
        return _err(tool_call_id, "name 必须为合法 Python 标识符。")
    params = [ToolParameterSpec(**p) for p in parameters if isinstance(p, dict)]
    try:
        meta = svc_scaffold_tool(
            agents_root=agents_root,
            agent_id=agent_id,
            name=name.strip(),
            description=description,
            parameters=params,
        )
        return _ok(
            tool_call_id,
            f"✅ Tool **{meta.name}** 脚手架生成成功！\n"
            f"- Agent: `{agent_id}`\n"
            f"- 文件: `{meta.file_path}`\n"
            "请打开文件，在 execute() 方法中实现具体逻辑。",
        )
    except FileNotFoundError:
        return _err(tool_call_id, "Agent 不存在。")
    except FileExistsError:
        return _err(tool_call_id, "同名工具文件已存在。")
    except ValueError as e:
        return _err(tool_call_id, f"参数错误：{e}")
    except Exception as e:
        logger.exception("create_tool failed")
        return _err(tool_call_id, f"生成工具脚手架时发生错误：{e}")


async def _do_update_tool(
    agents_root: Path,
    tool_call_id: str,
    agent_id: str,
    tool_name: str,
    content: str,
) -> AgentToolResult:
    bad = _validate_tool_name(tool_name, tool_call_id)
    if bad:
        return bad
    agent_dir = resolve_agent_dir(agents_root, agent_id)
    if not agent_dir:
        return _err(tool_call_id, "Agent 不存在。")
    tools_dir = agent_dir / "tools"
    if not tools_dir.is_dir():
        tools_dir.mkdir(parents=True)
    tool_file = tools_dir / f"{tool_name.strip()}.py"
    try:
        tool_file.write_text(content, encoding="utf-8")
        return _ok(tool_call_id, f"✅ 工具 {tool_name}.py 代码更新/生成成功！")
    except Exception as e:
        logger.exception("update_tool failed")
        return _err(tool_call_id, f"更新工具失败：{e}")


async def _do_delete_tool(
    agents_root: Path, tool_call_id: str, agent_id: str, tool_name: str
) -> AgentToolResult:
    bad = _validate_tool_name(tool_name, tool_call_id)
    if bad:
        return bad
    agent_dir = resolve_agent_dir(agents_root, agent_id)
    if not agent_dir:
        return _err(tool_call_id, "Agent 不存在。")
    tool_file = agent_dir / "tools" / f"{tool_name.strip()}.py"
    if not tool_file.is_file():
        return _err(tool_call_id, f"Tool {tool_name}.py 不存在。")
    try:
        os.remove(tool_file)
        return _ok(tool_call_id, f"✅ 工具 {tool_name}.py 已删除。")
    except Exception as e:
        logger.exception("delete_tool failed")
        return _err(tool_call_id, f"删除工具失败：{e}")


async def _do_read_tool(
    agents_root: Path, tool_call_id: str, agent_id: str, tool_name: str
) -> AgentToolResult:
    bad = _validate_tool_name(tool_name, tool_call_id)
    if bad:
        return bad
    agent_dir = resolve_agent_dir(agents_root, agent_id)
    if not agent_dir:
        return _err(tool_call_id, "Agent 不存在。")
    tool_file = agent_dir / "tools" / f"{tool_name.strip()}.py"
    if not tool_file.is_file():
        return _err(tool_call_id, f"Tool {tool_name}.py 不存在。")
    try:
        content = tool_file.read_text(encoding="utf-8")
        return _ok(tool_call_id, f"工具 {tool_name}.py 源码:\n```python\n{content}\n```")
    except Exception as e:
        logger.exception("read_tool failed")
        return _err(tool_call_id, f"读取工具失败：{e}")


class ManageToolsTool(AgentTool):
    """管理 Tool。create/update/delete 必须用户确认后传入 confirmation='我确认变更'。"""

    name = "manage_tools"
    description = (
        "[Tool 域] 管理原生工具。"
        " list/read: 无需确认。"
        " create/update/delete: 必须先让用户回复「我确认变更」并传入 confirmation='我确认变更'。"
        " list: 必填 agent_id。create: 必填 name。update: 必填 tool_name、content。delete/read: 必填 tool_name。"
    )
    parameters = [
        ToolParameter(
            name="action",
            type="string",
            description="操作：list | create | update | delete | read",
            required=True,
            enum=_ACTIONS,
        ),
        ToolParameter(
            name="agent_id",
            type="string",
            description="目标 Agent ID，不填则使用当前对话上下文中的 target_agent",
            required=False,
        ),
        ToolParameter(
            name="tool_name",
            type="string",
            description="工具模块名（无 .py 后缀，须为合法 Python 标识符）。create/update/delete/read 时使用",
            required=False,
        ),
        ToolParameter(
            name="name",
            type="string",
            description="工具名称（create 时必填，snake_case 如 check_policy）",
            required=False,
        ),
        ToolParameter(
            name="description",
            type="string",
            description="工具功能描述（create 时选填）",
            required=False,
        ),
        ToolParameter(
            name="parameters",
            type="array",
            description='create 时选填，参数定义 [{"name":"...", "description":"...", "type":"string", "required":true}]',
            required=False,
        ),
        ToolParameter(
            name="content",
            type="string",
            description="update 时必填，完整的 Python 源码内容",
            required=False,
        ),
        ToolParameter(
            name="confirmation",
            type="string",
            description="用户确认后必须传入「我确认变更」才会执行 create/update/delete",
            required=False,
        ),
    ]

    async def execute(self, tool_call: ToolCall, context: dict[str, Any] | None = None) -> AgentToolResult:
        args = tool_call.arguments or {}
        action = (args.get("action") or "").strip().lower()
        if action not in _ACTIONS:
            return _err(tool_call.id, f"action 必须为 {_ACTIONS} 之一。")

        agent_id = _resolve_agent_id(args, context)
        if not agent_id:
            return _err(
                tool_call.id,
                "需要指定 agent_id，或在当前 Agent 管理页打开 Meta-Agent 对话。",
            )

        agents_root = get_agents_root(__file__)

        if action == "list":
            return await _do_list_tools(agents_root, tool_call.id, agent_id)

        if action == "create":
            name = (read_string_param(args, "name", "") or "").strip()
            if not name:
                return _err(tool_call.id, "当 action=create 时，必须提供 name。")
            confirmation = read_string_param(args, "confirmation", None)
            if err := _require_confirmation(
                confirmation, tool_call.id, f"创建 Tool：{name}（Agent {agent_id}）"
            ):
                return err
            description = read_string_param(args, "description", "") or ""
            params_raw = read_list_param(args, "parameters", []) or []
            return await _do_create_tool(
                agents_root,
                tool_call.id,
                agent_id,
                name=name,
                description=description,
                parameters=params_raw,
            )

        tool_name = (read_string_param(args, "tool_name", "") or "").strip()
        if not tool_name:
            return _err(tool_call.id, f"当 action={action} 时，必须提供 tool_name。")

        if action == "update":
            content = read_string_param(args, "content", "") or ""
            if not content:
                return _err(tool_call.id, "当 action=update 时，必须提供 content。")
            confirmation = read_string_param(args, "confirmation", None)
            if err := _require_confirmation(
                confirmation, tool_call.id, f"更新 Tool：{tool_name}（Agent {agent_id}）"
            ):
                return err
            return await _do_update_tool(
                agents_root, tool_call.id, agent_id, tool_name, content
            )

        if action == "delete":
            confirmation = read_string_param(args, "confirmation", None)
            if err := _require_confirmation(
                confirmation, tool_call.id, f"删除 Tool：{tool_name}（Agent {agent_id}）"
            ):
                return err
            return await _do_delete_tool(agents_root, tool_call.id, agent_id, tool_name)

        if action == "read":
            return await _do_read_tool(agents_root, tool_call.id, agent_id, tool_name)

        return _err(tool_call.id, f"未实现的 action: {action}")
