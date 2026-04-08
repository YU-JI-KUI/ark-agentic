from __future__ import annotations

import logging
from typing import Optional

from .classifier import SetFitClassifier, SemanticClassifier
from .config import SkillMatcherConfig, SkillMatcherMode
from .loader import SkillLoader
from .matcher import SkillMatcher

logger = logging.getLogger(__name__)


class MatcherBuilder:
    """Constructs a SkillMatcher pre-configured with semantic classifiers."""

    def __init__(self, loader: SkillLoader, config: SkillMatcherConfig | None = None) -> None:
        self.loader = loader
        self.config = config or SkillMatcherConfig()

    def build(self) -> SkillMatcher:
        classifier = self._build_classifier()
        return SkillMatcher(self.loader, semantic_classifier=classifier)

    def _build_classifier(self) -> SemanticClassifier | None:
        mode = self.config.normalized_load_mode()
        if mode != SkillMatcherMode.semantic:
            logger.info("skill_load_mode=%s, semantic classifier not required", self.config.load_mode.value)
            return None

        semantic_config = self.config.semantic_classifier
        if semantic_config is None:
            logger.warning("SkillMatcherConfig semantic_classifier missing despite semantic mode")
            return None

        try:
            classifier = SetFitClassifier(
                model=semantic_config.setfit_model_path,
                max_full_inject=semantic_config.max_full_inject,
                energy_threshold=semantic_config.energy_threshold,
                margin_threshold=semantic_config.margin_threshold,
                skill_loader=self.loader,
            )
            logger.info("Initialized SemanticClassifier from %s", semantic_config.setfit_model_path)
            return classifier
        except Exception as exc:  # pragma: no cover - initialization failure handled by caller
            logger.error("Failed to initialize SemanticClassifier: %s", exc)
            return None


__all__ = [
    "MatcherBuilder",
]
