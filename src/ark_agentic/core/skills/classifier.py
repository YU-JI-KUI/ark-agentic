"""
语义分类器

将用户 query 与已通过资格检查的 skill 列表做语义分组，输出 full_inject / metadata_only。

主要实现：SetFitClassifier（有监督分类，适合口语短句）
备选实现：EmbeddingClassifier（无监督余弦匹配，仅原型验证）
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from ..types import SkillEntry

if TYPE_CHECKING:
    from .loader import SkillLoader

logger = logging.getLogger(__name__)


@dataclass
class _ClassifyResult:
    """内部分类结果，用于 full_inject / metadata_only 分组及日志"""

    full_inject: list[SkillEntry] = field(default_factory=list)
    metadata_only: list[SkillEntry] = field(default_factory=list)
    confidence: float = 0.0
    matched_tags: list[str] = field(default_factory=list)


@runtime_checkable
class SemanticClassifier(Protocol):
    """语义分类器接口，供 SkillMatcher 在 skill_load_mode=semantic 时使用。

    与 check_skill_eligibility / should_include_skill 同属 skill 选择链路：
    Matcher 先做策略与资格过滤，再调用 classifier 将「已匹配」技能分为 full / meta。
    """

    def classify(
        self, query: str, candidates: list[SkillEntry]
    ) -> tuple[list[SkillEntry], list[SkillEntry]]:
        """将候选技能分为全文注入与仅元数据两组

        Args:
            query: 用户输入
            candidates: 已通过资格检查的技能列表

        Returns:
            (full_inject, metadata_only)
        """
        ...


class SetFitClassifier:
    """基于 SetFit 的有监督语义分类器（生产推荐）

    使用 ModernBERT 作为 backbone，通过业务标注数据训练。
    适合保险/金融场景中用户口语短句（"我要理赔"、"取个款"）到业务 tag 的映射。

    训练数据格式：(query_text, tag_label) 对
        ("我想取钱", "withdrawal")
        ("车险理赔怎么办", "claims")

    双阈值决策（内部实现细节）：
    - Energy 检测：E(x) = -log Σ exp(logit_i)；低于阈值 → out-of-scope，全部 metadata_only
    - Margin 检测：top1 - top2 ≥ margin_threshold → 高置信 full_inject；否则 metadata_only

    Args:
        model: SetFit 模型路径或 HuggingFace repo；也可通过 ARK_SETFIT_MODEL 环境变量指定
        max_full_inject: 单次全文注入的最大 skill 数
        energy_threshold: Energy OOS 检测阈值（越低越保守）
        margin_threshold: top1-top2 margin 高置信阈值
        skill_loader: 提供 list_by_tag 能力（构造后可通过 bind_loader 绑定）
    """

    def __init__(
        self,
        model: str | None = None,
        *,
        max_full_inject: int = 7,
        energy_threshold: float = -20.0,
        margin_threshold: float = 0.3,
        skill_loader: SkillLoader | None = None,
    ) -> None:
        model_path = model or os.getenv("ARK_SETFIT_MODEL")
        if not model_path:
            raise ValueError(
                "SetFitClassifier requires a model path. "
                "Pass model='path/to/model' or set ARK_SETFIT_MODEL env var."
            )

        try:
            from setfit import SetFitModel  # type: ignore[import-untyped]
        except ImportError as e:
            raise ImportError(
                "setfit is required for SetFitClassifier. "
                "Install with: uv add 'ark-agentic[setfit]'"
            ) from e

        logger.info(f"Loading SetFit model from: {model_path}")
        self._model = SetFitModel.from_pretrained(model_path)
        self._max_full_inject = max_full_inject
        self._energy_threshold = energy_threshold
        self._margin_threshold = margin_threshold
        self._skill_loader = skill_loader
        logger.info("SetFitClassifier ready")

    def bind_loader(self, loader: SkillLoader) -> None:
        """绑定 SkillLoader 以支持 list_by_tag"""
        self._skill_loader = loader

    def classify(
        self, query: str, candidates: list[SkillEntry]
    ) -> tuple[list[SkillEntry], list[SkillEntry]]:
        """SemanticClassifier 接口：将候选分为 full_inject / metadata_only"""
        result = self._classify_impl(query, candidates)
        return (result.full_inject, result.metadata_only)

    def _classify_impl(self, query: str, candidates: list[SkillEntry]) -> _ClassifyResult:
        if not query.strip() or not candidates:
            return _ClassifyResult(metadata_only=list(candidates))

        import torch

        with torch.no_grad():
            outputs = self._model.model_body([query], convert_to_tensor=True)
            if hasattr(outputs, "pooler_output"):
                embeddings = outputs.pooler_output
            else:
                embeddings = outputs.last_hidden_state[:, 0, :]
            logits = self._model.model_head(embeddings)
            if hasattr(logits, "logits"):
                logits = logits.logits

        logits_np = logits.cpu().float().numpy()[0]

        import numpy as np

        energy = -float(np.log(np.sum(np.exp(logits_np - logits_np.max()))) + logits_np.max())
        if energy < self._energy_threshold:
            logger.debug(f"OOS detected (energy={energy:.2f}), all metadata_only")
            return _ClassifyResult(metadata_only=list(candidates), confidence=0.0)

        probs = np.exp(logits_np - logits_np.max())
        probs /= probs.sum()
        top_indices = np.argsort(probs)[::-1]
        top1_score = float(probs[top_indices[0]])
        top2_score = float(probs[top_indices[1]]) if len(top_indices) > 1 else 0.0
        margin = top1_score - top2_score

        id_to_label: dict[int, str] = self._model.model_head.config.id2label  # type: ignore[attr-defined]
        top1_tag = id_to_label.get(int(top_indices[0]), "")

        if margin >= self._margin_threshold and top1_tag:
            full_skills = self._get_skills_by_tag(top1_tag, candidates)
            remaining = [s for s in candidates if s not in full_skills]
            logger.debug(
                f"Classify: tag={top1_tag} margin={margin:.2f} "
                f"full={len(full_skills)} meta={len(remaining)}"
            )
            return _ClassifyResult(
                full_inject=full_skills,
                metadata_only=remaining,
                confidence=top1_score,
                matched_tags=[top1_tag],
            )

        logger.debug(f"Low margin ({margin:.2f}), all metadata_only")
        return _ClassifyResult(
            metadata_only=list(candidates), confidence=top1_score
        )

    def _get_skills_by_tag(self, tag: str, candidates: list[SkillEntry]) -> list[SkillEntry]:
        if self._skill_loader is not None:
            tagged = self._skill_loader.list_by_tag(tag)
            candidate_ids = {s.id for s in candidates}
            matched = [s for s in tagged if s.id in candidate_ids]
        else:
            matched = [s for s in candidates if tag in s.metadata.tags]
        return matched[: self._max_full_inject]


class EmbeddingClassifier:
    """基于 Embedding 余弦相似度的语义分类器（原型验证备选，不推荐生产）

    注意：对保险/金融口语短句效果差，生产请用 SetFitClassifier。
    适合快速验证 SemanticClassifier 接口，无需训练数据。

    Args:
        model_name: sentence-transformers 模型名（已在 dependencies 中）
        high_thresh: 余弦相似度阈值，≥ 此值才全文注入
        max_full_inject: 单次全文注入最大 skill 数
    """

    def __init__(
        self,
        model_name: str = "BAAI/bge-m3",
        *,
        high_thresh: float = 0.75,
        max_full_inject: int = 7,
    ) -> None:
        from sentence_transformers import SentenceTransformer

        logger.info(f"Loading embedding model: {model_name}")
        self._encoder = SentenceTransformer(model_name)
        self._high_thresh = high_thresh
        self._max_full_inject = max_full_inject
        self._skill_embeddings: dict[str, object] = {}

    def classify(
        self, query: str, candidates: list[SkillEntry]
    ) -> tuple[list[SkillEntry], list[SkillEntry]]:
        """SemanticClassifier 接口：将候选分为 full_inject / metadata_only"""
        result = self._classify_impl(query, candidates)
        return (result.full_inject, result.metadata_only)

    def _classify_impl(self, query: str, candidates: list[SkillEntry]) -> _ClassifyResult:
        if not query.strip() or not candidates:
            return _ClassifyResult(metadata_only=list(candidates))

        import numpy as np

        self._ensure_indexed(candidates)
        q_vec = self._encoder.encode(query, normalize_embeddings=True)

        scored: list[tuple[float, SkillEntry]] = []
        for skill in candidates:
            emb = self._skill_embeddings[skill.id]
            sim = float(np.dot(q_vec, emb))
            scored.append((sim, skill))

        scored.sort(key=lambda x: x[0], reverse=True)
        full: list[SkillEntry] = []
        meta: list[SkillEntry] = []
        for sim, skill in scored:
            if sim >= self._high_thresh and len(full) < self._max_full_inject:
                full.append(skill)
            else:
                meta.append(skill)

        confidence = scored[0][0] if scored else 0.0
        logger.debug(f"EmbeddingClassifier: full={len(full)} meta={len(meta)} top_sim={confidence:.3f}")
        return _ClassifyResult(
            full_inject=full,
            metadata_only=meta,
            confidence=confidence,
        )

    def _ensure_indexed(self, candidates: list[SkillEntry]) -> None:
        import numpy as np

        for skill in candidates:
            if skill.id not in self._skill_embeddings:
                text = f"{skill.metadata.name}: {skill.metadata.description}"
                self._skill_embeddings[skill.id] = self._encoder.encode(
                    text, normalize_embeddings=True
                )
