from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from ..types import SkillLoadMode


class SkillMatcherMode(Enum):
    """补充的技能匹配模式摘要，便于配置/策略文档。"""

    full = SkillLoadMode.full
    dynamic = SkillLoadMode.dynamic
    semantic = SkillLoadMode.semantic

    @classmethod
    def from_value(cls, value: SkillLoadMode | str) -> "SkillMatcherMode":
        """将 str/SkillLoadMode 统一映射到 SkillMatcherMode。"""
        if isinstance(value, SkillLoadMode):
            value = value.value
        try:
            return cls(value)
        except ValueError as exc:
            raise ValueError(f"Unsupported skill load mode: {value}") from exc


class SemanticClassifierConfig(BaseModel):
    """SetFit 语义分类器的参数配置。"""

    setfit_model_path: str = Field(
        ..., description="SetFit 模型的路径或 HuggingFace repo，用于语义分类。"
    )
    max_full_inject: int = Field(
        7,
        ge=0,
        description="single request 中最多注入多少个 full_skills，当超过时其余转为 metadata_only。",
    )
    energy_threshold: float = Field(
        -20.0,
        description="Energy 阈值：低于该值认为输入超出语义分类范围，全部转为 metadata_only。",
    )
    margin_threshold: float = Field(
        0.3,
        ge=0.0,
        description="top1-top2 margin 阈值，高于时视为高置信，可将对应技能归为 full_inject。",
    )

    @field_validator("setfit_model_path")
    @classmethod
    def _require_model_path(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("SetFit 模型路径不能为空，请在配置中指定 semantic_classifier.setfit_model_path。")
        return value.strip()


class SkillMatcherConfig(BaseModel):
    """技能匹配器配置，描述 load_mode 与语义分类器的使用方式。"""

    load_mode: SkillLoadMode = Field(
        SkillLoadMode.full,
        description="默认技能加载模式，影响 full_inject / metadata_only 的分配策略。",
    )
    semantic_classifier: SemanticClassifierConfig | None = Field(
        None,
        description="语义分类器的配置，在 skill_load_mode=semantic 时必须提供。",
    )

    @model_validator(mode="after")
    def _require_classifier_for_semantic(self) -> "SkillMatcherConfig":
        """semantic 模式下必须提供 semantic_classifier 配置。"""
        mode = SkillMatcherMode.from_value(self.load_mode)
        if mode == SkillMatcherMode.semantic and self.semantic_classifier is None:
            raise ValueError("请为 skill_load_mode='semantic' 配置 semantic_classifier 设置。")
        return self

    def normalized_load_mode(self) -> SkillMatcherMode:
        """返回规范化后的加载模式。"""
        return SkillMatcherMode.from_value(self.load_mode)


__all__ = [
    "SkillMatcherConfig",
    "SemanticClassifierConfig",
    "SkillMatcherMode",
]
