"""
read_skill 工具

Skill 一等公民模型：
- 正文由 runner 下一轮注入 system prompt 的 <active_skill> 段（以 `_active_skill_id` 为锚）
- 本工具只返回"加载凭证 digest"，避免正文以 tool_result 形式重复占用上下文
- 切换 skill 时，新 skill 正文直接替换 <active_skill>，旧正文随之退出上下文
"""

from __future__ import annotations

from typing import Any

from .base import AgentTool, ToolParameter, read_string_param
from ..skills.loader import SkillLoader
from ..types import AgentToolResult, ToolCall


class ReadSkillTool(AgentTool):
    """按 skill id 激活一个技能：更新 `_active_skill_id`，下一轮 system prompt 注入正文。"""

    name = "read_skill"
    visibility = "always"
    thinking_hint = "正在读取技能文档…"
    description = (
        "Activate one skill by its id. After this call, the full SKILL.md body "
        "will be injected as the current authoritative rules in the next turn's "
        "system prompt. MUST be called before following any skill from "
        "<available_skills>. Calling it with a different skill_id switches the "
        "active skill; there is no need to re-read the same skill within a session."
    )
    parameters = [
        ToolParameter(
            name="skill_id",
            type="string",
            description="The id of the skill to activate (from <available_skills>, e.g. insurance.withdraw_money)",
            required=True,
        ),
    ]

    def __init__(self, skill_loader: SkillLoader) -> None:
        self._loader = skill_loader

    async def execute(
        self, tool_call: ToolCall, context: dict[str, Any] | None = None
    ) -> AgentToolResult:
        """激活 skill 并返回简短 digest；正文由下一轮 system prompt 携带。"""
        args = tool_call.arguments or {}
        skill_id = read_string_param(args, "skill_id", "")

        if not skill_id or not skill_id.strip():
            return AgentToolResult.text_result(
                tool_call.id,
                "Error: skill_id is required and must be non-empty.",
            )

        skill_id = skill_id.strip()
        skill = self._loader.get_skill(skill_id)

        if skill is None:
            return AgentToolResult.text_result(
                tool_call.id,
                f"Error: unknown skill id '{skill_id}'. Use an id from the available skills list.",
            )

        digest = (
            f"Skill '{skill.metadata.name}' (id: {skill.id}) is now active. "
            f"Its full content is available in <active_skill> in the system prompt; "
            f"follow it as the authoritative rules for this turn."
        )
        return AgentToolResult.text_result(
            tool_call.id,
            digest,
            metadata={"state_delta": {"_active_skill_id": skill_id}},
        )
