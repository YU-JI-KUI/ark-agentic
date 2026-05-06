"""MetabuilderAgent — 内置对话式 Agent 构建助手"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from .factory import create_meta_builder_from_env

if TYPE_CHECKING:
    from ...core.registry import AgentRegistry

logger = logging.getLogger(__name__)

__all__ = [
    "create_meta_builder_from_env",
    "register",
]


def register(registry: "AgentRegistry", **_: Any) -> None:
    """Auto-discovery hook called by ``agents.register_all``.

    Skips if already registered (Studio used to register meta_builder
    itself; idempotency keeps both paths safe during migration). Errors
    during agent construction are logged and swallowed — meta_builder
    needs an LLM env config and can fail gracefully without blocking
    other agents.
    """
    if "meta_builder" in registry.list_ids():
        return
    try:
        registry.register("meta_builder", create_meta_builder_from_env())
    except Exception:
        logger.warning(
            "MetaBuilder init failed, agent not available", exc_info=True,
        )
