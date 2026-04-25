"""
技能基础配置和资格检查

参考: openclaw-main/src/agents/skills/types.ts, workspace.ts
"""

from __future__ import annotations

import os
import platform
import re
import shutil
from dataclasses import dataclass, field
from typing import Any, Callable

from ..types import SkillEntry, SkillLoadMode


@dataclass
class SkillConfig:
    """技能系统配置"""

    # 技能目录列表（按优先级排序，越前面优先级越高）
    skill_directories: list[str] = field(default_factory=list)

    # Agent ID，用于构建全局唯一的 skill id（格式: agent_id.skill_name）
    agent_id: str = ""

    # 是否启用资格检查
    enable_eligibility_check: bool = True

    # 默认调用策略
    default_invocation_policy: str = "auto"

    # 是否允许未知技能
    allow_unknown_skills: bool = False

    # Agent 级别加载模式
    load_mode: SkillLoadMode = SkillLoadMode.full

    # ≤ 此值扁平渲染, > 此值按 group 分组
    group_render_threshold: int = 10

    # 最大 skill 条数 (OpenClaw=150)
    max_skills_in_prompt: int = 100

    # 最大字符数 (≈12,500 token, post-compaction ~10%)
    max_skills_prompt_chars: int = 50_000


def check_skill_eligibility(
    skill: SkillEntry,
    context: dict[str, Any] | None = None,
) -> tuple[bool, list[str]]:
    """检查技能资格

    参考: openclaw-main/src/agents/skills/workspace.ts - checkSkillEligibility

    Args:
        skill: 技能条目
        context: 执行上下文（可包含额外的环境信息）

    Returns:
        (is_eligible, reasons) - 是否满足资格及原因列表
    """
    reasons: list[str] = []
    metadata = skill.metadata
    context = context or {}

    # 1. 检查操作系统
    if metadata.required_os:
        current_os = platform.system().lower()
        os_mapping = {"windows": "windows", "linux": "linux", "darwin": "darwin"}
        current_os_normalized = os_mapping.get(current_os, current_os)

        if current_os_normalized not in metadata.required_os:
            reasons.append(
                f"OS mismatch: requires {metadata.required_os}, got {current_os_normalized}"
            )

    # 2. 检查必需的二进制文件
    if metadata.required_binaries:
        for binary in metadata.required_binaries:
            if shutil.which(binary) is None:
                reasons.append(f"Binary not found: {binary}")

    # 3. 检查必需的环境变量
    if metadata.required_env_vars:
        for env_var in metadata.required_env_vars:
            if os.environ.get(env_var) is None:
                reasons.append(f"Environment variable not set: {env_var}")

    # 4. 检查必需的工具（从 context 中获取可用工具）
    if metadata.required_tools:
        available_tools = context.get("available_tools", set())
        for tool in metadata.required_tools:
            if tool not in available_tools:
                reasons.append(f"Required tool not available: {tool}")

    is_eligible = len(reasons) == 0
    return is_eligible, reasons


def should_include_skill(
    skill: SkillEntry,
    query: str | None = None,
    context: dict[str, Any] | None = None,
) -> bool:
    """判断是否应在当前上下文中包含技能

    参考: openclaw-main/src/agents/skills/workspace.ts

    Args:
        skill: 技能条目
        query: 用户查询（用于判断相关性）
        context: 执行上下文

    Returns:
        是否应包含该技能
    """
    # 检查是否启用
    if not skill.enabled:
        return False

    # 检查调用策略
    policy = skill.metadata.invocation_policy

    if policy == "always":
        return True
    elif policy == "manual":
        # 手动策略需要显式指定
        requested_skills = (context or {}).get("requested_skills", [])
        return skill.id in requested_skills
    else:  # auto
        # 自动策略：根据上下文判断
        # 简单实现：总是包含 auto 技能
        return True


def _escape_xml(text: str) -> str:
    """XML 特殊字符转义"""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


LOAD_ONE_SKILL_INSTRUCTIONS = """\
## 技能加载（mandatory — 回复或调用任何工具前必须先完成）
技能文档包含完整的业务规则、参数约束和输出格式。未读取技能就调用工具会违反业务规则。

流程：
1. 扫描 <available_skills> 的 <description>，找到与用户问题匹配的技能
2. 调用 `read_skill(skill_id)` 加载完整指令
3. 按返回的指令执行

多个技能匹配时选最具体的。仅当用户问题与所有技能完全无关时（如寒暄），才可跳过。
约束：每轮最多读取一个技能；必须先 read_skill 再调用其他工具。"""


def _truncate_description(desc: str, max_chars: int = 250) -> str:
    """Per-entry cap, 对齐 Claude Code 250 chars."""
    return desc if len(desc) <= max_chars else desc[: max_chars - 3] + "..."


def _render_skill_xml(skill: SkillEntry, indent: str = "  ") -> list[str]:
    desc = _truncate_description(skill.metadata.description)
    return [
        f"{indent}<skill>",
        f"{indent}  <id>{_escape_xml(skill.id)}</id>",
        f"{indent}  <name>{_escape_xml(skill.metadata.name)}</name>",
        f"{indent}  <description>{_escape_xml(desc)}</description>",
        f"{indent}</skill>",
    ]


def _format_flat_skills(skills: list[SkillEntry]) -> str:
    """≤ threshold: 扁平 XML."""
    lines = ["<available_skills>"]
    for skill in skills:
        lines.extend(_render_skill_xml(skill))
    lines.append("</available_skills>")
    return "\n".join(lines)


def _format_grouped_skills(skills: list[SkillEntry]) -> str:
    """> threshold: 按 metadata.group 分组, 无 group 归入 'other'."""
    from collections import defaultdict

    groups: dict[str, list[SkillEntry]] = defaultdict(list)
    for skill in skills:
        groups[skill.metadata.group or "other"].append(skill)

    lines = ["<available_skills>"]
    for group_name in sorted(groups):
        lines.append(f'  <group name="{_escape_xml(group_name)}">')
        for skill in groups[group_name]:
            lines.extend(_render_skill_xml(skill, indent="    "))
        lines.append("  </group>")
    lines.append("</available_skills>")
    return "\n".join(lines)


def _apply_budget(
    skills: list[SkillEntry],
    max_count: int,
    max_chars: int,
    formatter: Callable[[list[SkillEntry]], str],
) -> tuple[str, bool]:
    """1) max_count 截断  2) 二分搜索 max_chars 前缀  3) 附加 truncation 提示."""
    truncated = False
    subset = skills
    if len(subset) > max_count:
        subset = subset[:max_count]
        truncated = True

    text = formatter(subset)
    if len(text) <= max_chars:
        if truncated:
            text += f"\n(truncated: {len(skills) - len(subset)} more skills not shown)"
        return text, truncated

    lo, hi = 1, len(subset)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        candidate = formatter(subset[:mid])
        if len(candidate) <= max_chars:
            lo = mid
        else:
            hi = mid - 1

    text = formatter(subset[:lo])
    hidden = len(skills) - lo
    if hidden > 0:
        text += f"\n(truncated: {hidden} more skills not shown)"
    return text, True


def format_skills_metadata_for_prompt(
    skills: list[SkillEntry],
    config: SkillConfig | None = None,
) -> str:
    """格式化技能元数据为 XML（自适应扁平/分组 + 预算控制）。

    用于「仅元数据」模式：模型先看 <available_skills> 列表，
    再通过 read_skill 按需加载正文。
    """
    if not skills:
        return ""
    sc = config or SkillConfig()
    formatter = (
        _format_flat_skills
        if len(skills) <= sc.group_render_threshold
        else _format_grouped_skills
    )
    text, _ = _apply_budget(
        skills, sc.max_skills_in_prompt, sc.max_skills_prompt_chars, formatter,
    )
    return text


_LEADING_H1_RE = re.compile(r"^\s*#\s+.+", re.MULTILINE)


def _strip_leading_h1(content: str) -> str:
    """Remove the first ``# Title`` line if it appears at the very start.

    Skill bodies typically open with ``# 技能名称`` which duplicates the
    ``<skill name="...">`` attribute — stripping it avoids redundancy.
    Only the leading H1 is removed; deeper headings are kept intact.
    """
    stripped = content.lstrip("\n")
    m = _LEADING_H1_RE.match(stripped)
    if m:
        stripped = stripped[m.end():].lstrip("\n")
    return stripped


def render_skill_section(
    skills: list[SkillEntry],
    config: SkillConfig | None = None,
) -> str:
    """渲染 skill 系统提示段落（向后兼容）。

    full  → build_skill_prompt（全文注入）
    其它  → LOAD_ONE_SKILL_INSTRUCTIONS + format_skills_metadata_for_prompt（元数据 + read_skill）

    Note: SystemPromptBuilder.add_skills 是推荐入口，它会将 dynamic 模式的
    行为指令和元数据拆成独立 section，避免名词标签淹没指令。
    本函数保留给直接拼 prompt 字符串的场景。
    """
    if not skills:
        return ""
    sc = config or SkillConfig()
    if sc.load_mode == SkillLoadMode.full:
        return build_skill_prompt(skills)
    metadata = format_skills_metadata_for_prompt(skills, config=sc)
    if not metadata:
        return ""
    return LOAD_ONE_SKILL_INSTRUCTIONS.strip() + "\n\n" + metadata


def build_skill_prompt(skills: list[SkillEntry]) -> str:
    """构建 full-mode 技能提示文本。

    每个 skill 用 ``<skill>`` XML 标签包裹，避免 skill body 内部的
    markdown heading 与外层 ``## Available Skills`` 产生层级冲突。
    """
    if not skills:
        return ""

    sections: list[str] = []

    for skill in skills:
        sections.append(
            f'<skill name="{_escape_xml(skill.metadata.name)}" '
            f'description="{_escape_xml(skill.metadata.description)}">'
        )
        sections.append(_strip_leading_h1(skill.content))
        sections.append("</skill>\n")

    return "\n".join(sections)


def render_active_skill_section(skill: SkillEntry) -> str:
    """将当前激活的单个 skill 正文渲染为 <active_skill> XML 段。

    用于 dynamic 模式：与 <available_skills>（仅元数据）并存，
    形成 "可选项列表 → 当前激活正文 → 切换指引" 的自然顺序。

    切换 skill 时，此段跟随 session.state['_active_skill_id'] 每轮重建，
    system prompt 成为 skill 的"配置载体"，tool_result 只需记录加载凭证。
    """
    body = _strip_leading_h1(skill.content)
    return (
        f'<active_skill id="{_escape_xml(skill.id)}" '
        f'name="{_escape_xml(skill.metadata.name)}">\n'
        f'{body}\n'
        f'</active_skill>'
    )
