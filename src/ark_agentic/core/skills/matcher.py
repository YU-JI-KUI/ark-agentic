"""
技能匹配器

参考: openclaw-main/src/agents/skills/workspace.ts
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from ..types import SkillEntry
from .base import (
    build_skill_prompt,
    check_skill_eligibility,
    should_include_skill,
)
from .loader import SkillLoader

logger = logging.getLogger(__name__)


@dataclass
class SkillMatchResult:
    """技能匹配结果"""

    # 匹配到的技能列表
    matched_skills: list[SkillEntry] = field(default_factory=list)

    # 因资格不满足而排除的技能
    ineligible_skills: list[tuple[SkillEntry, list[str]]] = field(default_factory=list)

    # 因策略排除的技能
    excluded_skills: list[SkillEntry] = field(default_factory=list)

    @property
    def skill_ids(self) -> list[str]:
        """匹配的技能 ID 列表"""
        return [s.id for s in self.matched_skills]


class SkillMatcher:
    """技能匹配器

    根据上下文匹配可用技能，执行资格检查和策略过滤。
    """

    def __init__(self, loader: SkillLoader) -> None:
        self.loader = loader

    def match(
        self,
        query: str | None = None,
        context: dict[str, Any] | None = None,
        skill_ids: list[str] | None = None,
        check_eligibility: bool = True,
    ) -> SkillMatchResult:
        """匹配技能

        Args:
            query: 用户查询（用于相关性判断）
            context: 执行上下文
            skill_ids: 指定的技能 ID 列表（None 表示全部）
            check_eligibility: 是否检查资格

        Returns:
            匹配结果
        """
        result = SkillMatchResult()
        context = context or {}

        # 获取候选技能
        if skill_ids:
            candidates = [
                self.loader.get_skill(sid)
                for sid in skill_ids
                if self.loader.get_skill(sid)
            ]
        else:
            candidates = self.loader.list_skills()

        for skill in candidates:
            if skill is None:
                continue

            # 1. 检查是否应包含（策略过滤）
            if not should_include_skill(skill, query, context):
                result.excluded_skills.append(skill)
                continue

            # 2. 检查资格
            if check_eligibility:
                is_eligible, reasons = check_skill_eligibility(skill, context)
                if not is_eligible:
                    result.ineligible_skills.append((skill, reasons))
                    logger.debug(f"Skill {skill.id} ineligible: {reasons}")
                    continue

            # 3. 匹配成功
            result.matched_skills.append(skill)

        logger.info(
            f"Matched {len(result.matched_skills)} skills, "
            f"{len(result.ineligible_skills)} ineligible, "
            f"{len(result.excluded_skills)} excluded"
        )

        return result

    def match_for_prompt(
        self,
        query: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> str:
        """匹配技能并生成提示文本

        Args:
            query: 用户查询
            context: 执行上下文

        Returns:
            技能提示文本（可直接注入系统提示）
        """
        result = self.match(query=query, context=context)
        return build_skill_prompt(result.matched_skills)

    def get_skill_by_tag(self, tag: str) -> list[SkillEntry]:
        """按标签获取技能"""
        return [
            skill
            for skill in self.loader.list_skills()
            if tag in skill.metadata.tags
        ]

    def get_skill_by_group(self, group: str) -> list[SkillEntry]:
        """按分组获取技能"""
        return [
            skill
            for skill in self.loader.list_skills()
            if skill.metadata.group == group
        ]
