"""
manage_skills — 复合工具：Skill 的 list / create / update / delete / read

create/update/delete 必须先让用户回复「我确认变更」后，再次调用并传入 confirmation='我确认变更'。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ark_agentic.core.tools.base import AgentTool, ToolParameter, read_string_param
from ark_agentic.core.types import AgentToolResult, ToolCall
from ark_agentic.core.utils.env import get_agents_root
from ark_agentic.studio.services.skill_service import (
    create_skill as svc_create_skill,
    update_skill as svc_update_skill,
    delete_skill as svc_delete_skill,
    list_skills as svc_list_skills,
    parse_skill_dir,
)
from ark_agentic.core.utils.env import resolve_agent_dir

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


async def _do_list_skills(
    agents_root: Path, tool_call_id: str, agent_id: str
) -> AgentToolResult:
    try:
        skills = svc_list_skills(agents_root, agent_id)
    except FileNotFoundError as e:
        return _err(tool_call_id, "Agent 不存在。")
    except Exception as e:
        logger.exception("list_skills failed")
        return _err(tool_call_id, f"列出技能失败：{e}")
    if not skills:
        return _ok(tool_call_id, f"Agent {agent_id} 还没有任何技能。")
    lines = [f"Agent {agent_id} 的技能列表:"]
    for s in skills:
        lines.append(f"- **{s.id}** ({s.name}): {s.description or ''}")
    return _ok(tool_call_id, "\n".join(lines))


async def _do_create_skill(
    agents_root: Path,
    tool_call_id: str,
    agent_id: str,
    name: str,
    description: str,
    content: str,
) -> AgentToolResult:
    try:
        meta = svc_create_skill(
            agents_root=agents_root,
            agent_id=agent_id,
            name=name,
            description=description,
            content=content,
        )
        return _ok(
            tool_call_id,
            f"✅ Skill **{meta.name}** 创建成功！\n"
            f"- Agent: `{agent_id}`\n"
            f"- 文件: `{meta.file_path}`\n"
            "刷新 Skills 面板即可看到新技能。",
        )
    except FileNotFoundError:
        return _err(tool_call_id, "Agent 不存在。")
    except FileExistsError:
        return _err(tool_call_id, "同名技能已存在。")
    except ValueError as e:
        return _err(tool_call_id, f"参数错误：{e}")
    except Exception as e:
        logger.exception("create_skill failed")
        return _err(tool_call_id, f"创建技能时发生错误：{e}")


async def _do_update_skill(
    agents_root: Path,
    tool_call_id: str,
    agent_id: str,
    skill_id: str,
    name: str | None,
    description: str | None,
    content: str | None,
) -> AgentToolResult:
    if not any([name, description is not None, content is not None]):
        return _err(tool_call_id, "update 时请至少指定 name、description 或 content 之一。")
    try:
        meta = svc_update_skill(
            agents_root=agents_root,
            agent_id=agent_id,
            skill_id=skill_id,
            name=name,
            description=description,
            content=content,
        )
        return _ok(
            tool_call_id,
            f"✅ Skill **{meta.name}** 更新成功！\n- Agent: `{agent_id}`\n- 文件: `{meta.file_path}`",
        )
    except FileNotFoundError:
        return _err(tool_call_id, "Agent 或技能不存在。")
    except Exception as e:
        logger.exception("update_skill failed")
        return _err(tool_call_id, f"更新技能时发生错误：{e}")


async def _do_delete_skill(
    agents_root: Path, tool_call_id: str, agent_id: str, skill_id: str
) -> AgentToolResult:
    try:
        svc_delete_skill(agents_root, agent_id, skill_id)
        return _ok(tool_call_id, f"✅ 技能 {skill_id} 删除成功。")
    except FileNotFoundError:
        return _err(tool_call_id, "Agent 或技能不存在。")
    except ValueError as e:
        return _err(tool_call_id, f"参数错误：{e}")
    except Exception as e:
        logger.exception("delete_skill failed")
        return _err(tool_call_id, f"删除技能失败：{e}")


async def _do_read_skill(
    agents_root: Path, tool_call_id: str, agent_id: str, skill_id: str
) -> AgentToolResult:
    agent_dir = resolve_agent_dir(agents_root, agent_id)
    if not agent_dir:
        return _err(tool_call_id, "Agent 不存在。")
    skill_dir = agent_dir / "skills" / skill_id
    if not skill_dir.is_dir():
        return _err(tool_call_id, "技能不存在。")
    meta = parse_skill_dir(skill_dir)
    if not meta:
        return _err(tool_call_id, "无法解析技能内容。")
    return _ok(tool_call_id, f"技能 {meta.name} 内容:\n```markdown\n{meta.content}\n```")


class ManageSkillsTool(AgentTool):
    """管理 Skill。create/update/delete 必须用户确认后传入 confirmation='我确认变更'。"""

    name = "manage_skills"
    thinking_hint = "正在管理技能配置…"
    description = (
        "[Skill 域] 管理技能。"
        " list/read: 无需确认。"
        " create/update/delete: 必须先让用户回复「我确认变更」并传入 confirmation='我确认变更'。"
        " list: 必填 agent_id（可来自上下文）。create: 必填 name。update/delete/read: 必填 skill_id。"
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
            name="skill_id",
            type="string",
            description="技能 ID（目录名）。update/delete/read 时必填",
            required=False,
        ),
        ToolParameter(
            name="name",
            type="string",
            description="技能名称（create 必填，update 选填）",
            required=False,
        ),
        ToolParameter(
            name="description",
            type="string",
            description="技能描述（create/update 选填）",
            required=False,
        ),
        ToolParameter(
            name="content",
            type="string",
            description="SKILL.md 正文（create/update 选填，Markdown）",
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
            return await _do_list_skills(agents_root, tool_call.id, agent_id)

        if action == "create":
            name = (read_string_param(args, "name", "") or "").strip()
            if not name:
                return _err(tool_call.id, "当 action=create 时，必须提供 name。")
            confirmation = read_string_param(args, "confirmation", None)
            if err := _require_confirmation(
                confirmation, tool_call.id, f"创建 Skill：{name}（Agent {agent_id}）"
            ):
                return err
            description = read_string_param(args, "description", "") or ""
            content = read_string_param(args, "content", "") or ""
            return await _do_create_skill(
                agents_root, tool_call.id, agent_id, name, description, content
            )

        skill_id = (read_string_param(args, "skill_id", "") or "").strip()
        if not skill_id:
            return _err(tool_call.id, f"当 action={action} 时，必须提供 skill_id。")

        if action == "update":
            confirmation = read_string_param(args, "confirmation", None)
            if err := _require_confirmation(
                confirmation, tool_call.id, f"更新 Skill：{skill_id}（Agent {agent_id}）"
            ):
                return err
            name = read_string_param(args, "name", None)
            description = read_string_param(args, "description", None)
            content = read_string_param(args, "content", None)
            return await _do_update_skill(
                agents_root, tool_call.id, agent_id, skill_id, name, description, content
            )

        if action == "delete":
            confirmation = read_string_param(args, "confirmation", None)
            if err := _require_confirmation(
                confirmation, tool_call.id, f"删除 Skill：{skill_id}（Agent {agent_id}）"
            ):
                return err
            return await _do_delete_skill(agents_root, tool_call.id, agent_id, skill_id)

        if action == "read":
            return await _do_read_skill(agents_root, tool_call.id, agent_id, skill_id)

        return _err(tool_call.id, f"未实现的 action: {action}")
