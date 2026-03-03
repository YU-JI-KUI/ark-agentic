"""
manage_agents — 复合工具：Agent 的 list / create

必填约定：list 无需参数；create 必填 name，选填 description、skills。
agent_id 仅 create 不需要（创建的是新 Agent）；list 不需要。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ark_agentic.core.tools.base import AgentTool, ToolParameter, read_string_param, read_list_param
from ark_agentic.core.types import AgentToolResult, ToolCall
from ark_agentic.core.utils.env import get_agents_root
from ark_agentic.studio.services.agent_service import AgentScaffoldSpec, list_agents as svc_list_agents, scaffold_agent

logger = logging.getLogger(__name__)

_ACTIONS = ["list", "create"]


def _err(tool_call_id: str, msg: str) -> AgentToolResult:
    return AgentToolResult.error_result(tool_call_id, msg)


def _ok(tool_call_id: str, msg: str) -> AgentToolResult:
    return AgentToolResult.text_result(tool_call_id, msg)


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


class ManageAgentsTool(AgentTool):
    """管理 Agent：列出或创建。一次调用仅执行一个 action。"""

    name = "manage_agents"
    description = (
        "[Agent 域] 管理 Agent。"
        " list: 无需参数，列出所有 Agent。"
        " create: 必填 name，选填 description、skills（格式 [{\"name\":\"...\", \"description\":\"...\", \"content\":\"...\"}]）。"
    )
    parameters = [
        ToolParameter(
            name="action",
            type="string",
            description="操作：list（列出所有 Agent）或 create（创建新 Agent）",
            required=True,
            enum=_ACTIONS,
        ),
        ToolParameter(
            name="name",
            type="string",
            description="Agent 显示名称（create 时必填，中英文均可）",
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
    ]

    async def execute(self, tool_call: ToolCall, context: dict[str, Any] | None = None) -> AgentToolResult:
        args = tool_call.arguments or {}
        action = (args.get("action") or "").strip().lower()
        if action not in _ACTIONS:
            return _err(tool_call.id, f"action 必须为 {_ACTIONS} 之一，当前为：{action!r}")

        agents_root = get_agents_root(__file__)

        if action == "list":
            return await _do_list_agents(agents_root, tool_call.id)

        if action == "create":
            name = read_string_param(args, "name", "") or ""
            if not name.strip():
                return _err(tool_call.id, "当 action=create 时，必须提供 name。")
            description = read_string_param(args, "description", "") or ""
            skills_raw = read_list_param(args, "skills", []) or []
            return await _do_create_agent(
                agents_root,
                tool_call.id,
                name=name.strip(),
                description=description,
                skills=skills_raw,
            )

        return _err(tool_call.id, f"未实现的 action: {action}")
