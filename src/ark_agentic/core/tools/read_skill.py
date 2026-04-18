"""
read_skill 工具

在「仅元数据」模式下，模型通过此工具按 skill id 加载一个技能的完整 SKILL.md 内容。
"""

from __future__ import annotations

from typing import Any

from .base import AgentTool, ToolParameter, read_string_param
from ..skills.loader import SkillLoader
from ..types import AgentToolResult, ToolCall


class ReadSkillTool(AgentTool):
    """按 skill id 加载一个技能的完整内容（SKILL.md 正文 + frontmatter 解析后的元数据）。"""

    name = "read_skill"
    visibility = "always"
    thinking_hint = "正在读取技能文档…"
    description = (
        "Load the full SKILL.md content of one skill by its id. "
        "MUST be called before following any skill from <available_skills>. "
        "The skill metadata is only a summary — call this to get complete "
        "execution steps, output format, and constraints."
    )
    parameters = [
        ToolParameter(
            name="skill_id",
            type="string",
            description="The id of the skill to load (from <available_skills>, e.g. insurance.withdraw_money)",
            required=True,
        ),
    ]

    def __init__(self, skill_loader: SkillLoader) -> None:
        self._loader = skill_loader

    async def execute(
        self, tool_call: ToolCall, context: dict[str, Any] | None = None
    ) -> AgentToolResult:
        """返回指定 id 的技能完整内容，或明确错误信息。"""
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

        # 返回完整内容：frontmatter 已解析到 metadata，这里返回原始文件内容更完整（含正文）
        # 我们返回 skill.content（正文）+ 元数据摘要，便于模型使用
        parts = [
            f"# {skill.metadata.name} (id: {skill.id})",
            f"_{skill.metadata.description}_",
            "",
            skill.content,
        ]
        return AgentToolResult.text_result(
            tool_call.id,
            "\n".join(parts),
            metadata={"state_delta": {"_active_skill_id": skill_id}},
        )
