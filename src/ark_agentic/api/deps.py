"""
API 共享依赖

将 AgentRegistry 的获取和 Agent 查找逻辑统一到此处，
供 chat.py 及 studio 各模块共享使用。
"""

from __future__ import annotations

from fastapi import HTTPException

from ark_agentic.core.registry import AgentRegistry
from ark_agentic.core.runner import AgentRunner

# 由 app.py 在启动时调用 init_registry() 设置一次
_registry: AgentRegistry | None = None


def init_registry(registry: AgentRegistry) -> None:
    """由 app.py 调用一次，设置共享 registry。全局唯一入口。"""
    global _registry
    _registry = registry


def get_registry() -> AgentRegistry:
    """获取共享 AgentRegistry 实例。"""
    assert _registry is not None, "deps.init_registry() must be called before use"
    return _registry


def get_agent(agent_id: str) -> AgentRunner:
    """按 agent_id 获取 AgentRunner，找不到时返回 404。"""
    try:
        return get_registry().get(agent_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")
