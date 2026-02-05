"""
技能基础配置和资格检查

参考: openclaw-main/src/agents/skills/types.ts, workspace.ts
"""

from __future__ import annotations

import os
import platform
import shutil
from dataclasses import dataclass, field
from typing import Any

from ..types import SkillEntry, SkillMetadata


@dataclass
class SkillConfig:
    """技能系统配置"""

    # 技能目录列表（按优先级排序，越前面优先级越高）
    skill_directories: list[str] = field(default_factory=list)

    # 是否启用资格检查
    enable_eligibility_check: bool = True

    # 默认调用策略
    default_invocation_policy: str = "auto"

    # 是否允许未知技能
    allow_unknown_skills: bool = False


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


# 别名函数，保持向后兼容
check_skill_requirements = check_skill_eligibility


def build_skill_prompt(skills: list[SkillEntry]) -> str:
    """构建技能提示文本

    参考: openclaw-main/src/agents/skills/workspace.ts - buildEligibleSkillPrompt

    Args:
        skills: 要包含的技能列表

    Returns:
        格式化的技能提示文本
    """
    if not skills:
        return ""

    sections = ["## Available Skills\n"]

    for skill in skills:
        # 技能标题
        sections.append(f"### {skill.metadata.name}")
        sections.append(f"_{skill.metadata.description}_\n")

        # 技能内容（SKILL.md 的主体）
        sections.append(skill.content)
        sections.append("")  # 空行分隔

    return "\n".join(sections)
