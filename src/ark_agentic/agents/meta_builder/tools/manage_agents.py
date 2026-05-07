"""
manage_agents — 复合工具：Agent 的 list / create / delete

必填约定：list 无需参数；create 必填 name 且需用户确认；delete 必填 agent_id 且需用户确认。
所有增删改必须先让用户回复「我确认变更」后，再次调用并传入 confirmation='我确认变更'。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ark_agentic.core.tools.base import AgentTool, ToolParameter, read_string_param, read_list_param
from ark_agentic.core.types import AgentToolResult, ToolCall
from ark_agentic.core.utils.env import get_agents_root
from ark_agentic.plugins.studio.services.agent_service import (
    AgentScaffoldSpec,
    list_agents as svc_list_agents,
    scaffold_agent,
    delete_agent as svc_delete_agent,
)

logger = logging.getLogger(__name__)

CONFIRMATION_PHRASE = "我确认变更"
_ACTIONS = ["list", "create", "delete"]


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


async def _do_list_agents(agents_root: Path, tool_call_id: str) -> AgentToolResult:
    try:
        agents = svc_list_agents(agents_root)
    except Exception as e:
        logger.exception("list_agents failed")
        return _err(tool_call_id, f"列出 Agent 失败：{e}")
    if not agents:
        return _ok(tool_call_id, "当前没有任何 Agent。")
    lines = [f"共找到 {len(agents)} 个 Agent："]
    for a in agents:
        lines.append(f"- **{a.name}** (id: `{a.id}`): {a.description or '无描述'}")
    return _ok(tool_call_id, "\n".join(lines))


async def _do_create_agent(
    agents_root: Path,
    tool_call_id: str,
    name: str,
    description: str,
    skills: list[dict],
) -> AgentToolResult:
    spec = AgentScaffoldSpec(
        name=name,
        description=description or "",
        skills=[s for s in skills if isinstance(s, dict)],
    )
    try:
        agent_dir = scaffold_agent(agents_root, spec)
        return _ok(
            tool_call_id,
            f"✅ Agent **{name}** 创建成功！\n"
            f"- 目录: `{agent_dir}`\n"
            f"- 初始技能数: {len(spec.skills)}\n"
            "刷新 Dashboard 即可看到新 Agent。",
        )
    except FileExistsError as e:
        return _err(tool_call_id, f"创建失败：同名 Agent 已存在。请换一个名称。")
    except ValueError as e:
        return _err(tool_call_id, f"参数错误：{e}")
    except Exception as e:
        logger.exception("create_agent failed")
        return _err(tool_call_id, f"创建 Agent 时发生错误：{e}")


async def _do_delete_agent(
    agents_root: Path, tool_call_id: str, agent_id: str
) -> AgentToolResult:
    try:
        svc_delete_agent(agents_root, agent_id)
        return _ok(tool_call_id, f"✅ Agent **{agent_id}** 已删除。")
    except ValueError as e:
        return _err(tool_call_id, str(e))
    except FileNotFoundError:
        return _err(tool_call_id, "Agent 不存在。")
    except Exception as e:
        logger.exception("delete_agent failed")
        return _err(tool_call_id, f"删除 Agent 时发生错误：{e}")


class ManageAgentsTool(AgentTool):
    """管理 Agent：列出、创建或删除。create/delete 必须用户确认后传入 confirmation='我确认变更'。"""

    name = "manage_agents"
    thinking_hint = "正在管理智能体配置…"
    description = (
        "[Agent 域] 管理 Agent。"
        " list: 无需参数。"
        " create: 必填 name，选填 description、skills；执行前必须让用户回复「我确认变更」并传入 confirmation='我确认变更'。"
        " delete: 必填 agent_id；执行前必须用户确认并传入 confirmation='我确认变更'。不能删除 meta_builder。"
    )
    parameters = [
        ToolParameter(
            name="action",
            type="string",
            description="操作：list | create | delete",
            required=True,
            enum=_ACTIONS,
        ),
        ToolParameter(
            name="name",
            type="string",
            description="Agent 显示名称（create 时必填）",
            required=False,
        ),
        ToolParameter(
            name="description",
            type="string",
            description="Agent 功能描述（create 时选填）",
            required=False,
        ),
        ToolParameter(
            name="skills",
            type="array",
            description='create 时选填，初始技能列表 [{"name":"...", "description":"...", "content":"..."}]',
            required=False,
        ),
        ToolParameter(
            name="agent_id",
            type="string",
            description="要删除的 Agent ID（delete 时必填）",
            required=False,
        ),
        ToolParameter(
            name="confirmation",
            type="string",
            description="用户确认后必须传入「我确认变更」才会执行 create/delete",
            required=False,
        ),
    ]

    async def execute(self, tool_call: ToolCall, context: dict[str, Any] | None = None) -> AgentToolResult:
        args = tool_call.arguments or {}
        action = (args.get("action") or "").strip().lower()
        if action not in _ACTIONS:
            return _err(tool_call.id, f"action 必须为 {_ACTIONS} 之一，当前为：{action!r}")

        agents_root = get_agents_root()

        if action == "list":
            return await _do_list_agents(agents_root, tool_call.id)

        if action == "create":
            name = read_string_param(args, "name", "") or ""
            if not name.strip():
                return _err(tool_call.id, "当 action=create 时，必须提供 name。")
            confirmation = read_string_param(args, "confirmation", None)
            if err := _require_confirmation(
                confirmation, tool_call.id, f"创建 Agent：{name.strip()}"
            ):
                return err
            description = read_string_param(args, "description", "") or ""
            skills_raw = read_list_param(args, "skills", []) or []
            return await _do_create_agent(
                agents_root,
                tool_call.id,
                name=name.strip(),
                description=description,
                skills=skills_raw,
            )

        if action == "delete":
            agent_id = (read_string_param(args, "agent_id", "") or "").strip()
            if not agent_id:
                return _err(tool_call.id, "当 action=delete 时，必须提供 agent_id。")
            confirmation = read_string_param(args, "confirmation", None)
            if err := _require_confirmation(
                confirmation, tool_call.id, f"删除 Agent：{agent_id}"
            ):
                return err
            return await _do_delete_agent(agents_root, tool_call.id, agent_id)

        return _err(tool_call.id, f"未实现的 action: {action}")
