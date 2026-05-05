"""证券资产管理 Agent"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .agent import create_securities_agent

if TYPE_CHECKING:
    from ...core.registry import AgentRegistry

__all__ = [
    "create_securities_agent",
    "register",
]


def register(
    registry: "AgentRegistry",
    *,
    enable_memory: bool = False,
    enable_dream: bool = False,
    **_: Any,
) -> None:
    """Auto-discovery hook called by ``agents.register_all``."""
    registry.register("securities", create_securities_agent(
        enable_memory=enable_memory,
        enable_dream=enable_dream,
    ))
