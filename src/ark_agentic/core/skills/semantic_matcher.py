"""
语义技能匹配器 — 占位接口

未来实现方案：
- 基于 Embedding 的向量匹配 (BGE-M3 / Qwen3-Embedding)
- 基于 BERT fine-tune 的意图分类
- 基于 semantic-router 的 Route 匹配
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from ..types import SkillEntry


@dataclass
class SemanticMatchResult:
    """语义匹配结果

    将 skill 按置信度分为三档：
    - high_confidence: 直接全文注入系统提示
    - medium_confidence: 注入 metadata，让 LLM 调用 read_skill 选择
    - low_confidence: 不注入（减少 prompt 噪音）
    """

    high_confidence: list[SkillEntry] = field(default_factory=list)
    medium_confidence: list[SkillEntry] = field(default_factory=list)
    low_confidence: list[SkillEntry] = field(default_factory=list)


@runtime_checkable
class SemanticSkillMatcher(Protocol):
    """语义技能匹配器接口

    实现此接口以提供工程化的 skill 匹配能力。
    在 AgentRunner 中通过 `skill_load_mode="semantic"` 激活。

    示例实现思路::

        class EmbeddingSkillMatcher:
            def __init__(self, model_name: str = "BAAI/bge-m3"):
                self.encoder = SentenceTransformer(model_name)
                self._skill_embeddings: dict[str, np.ndarray] = {}

            def index_skills(self, skills: list[SkillEntry]) -> None:
                for skill in skills:
                    text = f"{skill.metadata.name}: {skill.metadata.description}"
                    self._skill_embeddings[skill.id] = self.encoder.encode(text)

            def match(self, query: str, skills: list[SkillEntry]) -> SemanticMatchResult:
                query_vec = self.encoder.encode(query)
                result = SemanticMatchResult()
                for skill in skills:
                    sim = cosine_similarity(query_vec, self._skill_embeddings[skill.id])
                    if sim > 0.8:
                        result.high_confidence.append(skill)
                    elif sim > 0.5:
                        result.medium_confidence.append(skill)
                    else:
                        result.low_confidence.append(skill)
                return result
    """

    def match(
        self, query: str, skills: list[SkillEntry]
    ) -> SemanticMatchResult:
        """根据用户查询匹配技能

        Args:
            query: 用户查询文本
            skills: 候选技能列表

        Returns:
            按置信度分层的匹配结果
        """
        ...
