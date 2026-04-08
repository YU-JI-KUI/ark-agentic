"""
技能匹配器

参考: openclaw-main/src/agents/skills/workspace.ts

与 base.check_skill_eligibility / should_include_skill 统一：先策略与资格过滤，
再按 SkillLoadMode（full/dynamic/semantic）决定 full_inject 与 metadata_only 分组。
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
from .classifier import SemanticClassifier

logger = logging.getLogger(__name__)


@dataclass
class SkillMatchResult:
    """技能匹配结果

    按注入方式分为 full_inject（全文注入 prompt）与 metadata_only（仅元数据 + read_skill）。
    matched_skills 为二者合并，用于向后兼容。
    """

    full_inject: list[SkillEntry] = field(default_factory=list)
    """全文注入 system prompt 的技能"""

    metadata_only: list[SkillEntry] = field(default_factory=list)
    """仅注入元数据，由 LLM 通过 read_skill 按需加载"""

    ineligible_skills: list[tuple[SkillEntry, list[str]]] = field(default_factory=list)
    excluded_skills: list[SkillEntry] = field(default_factory=list)

    @property
    def matched_skills(self) -> list[SkillEntry]:
        """匹配的技能列表（full_inject + metadata_only），向后兼容"""
        return self.full_inject + self.metadata_only

    @property
    def skill_ids(self) -> list[str]:
        """匹配的技能 ID 列表"""
        return [s.id for s in self.matched_skills]


class SkillMatcher:
    """技能匹配器

    根据上下文匹配可用技能：策略过滤、资格检查，再按 skill_load_mode 决定注入方式。
    semantic 模式下依赖 SemanticClassifier 做 full / metadata 分组。
    """

    def __init__(
        self,
        loader: SkillLoader,
        semantic_classifier: SemanticClassifier | None = None,
    ) -> None:
        self.loader = loader
        self.semantic_classifier = semantic_classifier

    def match(
        self,
        query: str | None = None,
        context: dict[str, Any] | None = None,
        skill_ids: list[str] | None = None,
        check_eligibility: bool = True,
        skill_load_mode: str = "full",
    ) -> SkillMatchResult:
        """匹配技能并按 mode 分配 full_inject / metadata_only

        Args:
            query: 用户查询（用于相关性/语义分类）
            context: 执行上下文
            skill_ids: 指定的技能 ID 列表（None 表示全部）
            check_eligibility: 是否检查资格
            skill_load_mode: full | dynamic | semantic

        Returns:
            SkillMatchResult（full_inject + metadata_only）
        """
        result = SkillMatchResult()
        context = context or {}
        matched: list[SkillEntry] = []

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

            if not should_include_skill(skill, query, context):
                result.excluded_skills.append(skill)
                continue

            if check_eligibility:
                is_eligible, reasons = check_skill_eligibility(skill, context)
                if not is_eligible:
                    result.ineligible_skills.append((skill, reasons))
                    logger.debug(f"Skill {skill.id} ineligible: {reasons}")
                    continue

            matched.append(skill)

        if skill_load_mode == "full":
            result.full_inject = list(matched)
            result.metadata_only = []
        elif skill_load_mode == "dynamic":
            result.full_inject = []
            result.metadata_only = list(matched)
        elif skill_load_mode == "semantic" and self.semantic_classifier is not None:
            full, meta = self.semantic_classifier.classify(query or "", matched)
            result.full_inject = full
            result.metadata_only = meta
            logger.info(
                f"Semantic: full_inject={len(full)} metadata_only={len(meta)}"
            )
        else:
            if skill_load_mode == "semantic":
                logger.info(
                    "skill_load_mode='semantic' but no semantic_classifier, "
                    "falling back to 'dynamic'"
                )
            result.full_inject = []
            result.metadata_only = list(matched)

        logger.info(
            f"Matched {len(result.matched_skills)} skills "
            f"(full={len(result.full_inject)} meta={len(result.metadata_only)}), "
            f"{len(result.ineligible_skills)} ineligible, "
            f"{len(result.excluded_skills)} excluded"
        )

        return result

    def match_for_prompt(
        self,
        query: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> str:
        """匹配技能并生成提示文本"""
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
