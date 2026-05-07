"""
Agent 注册表

管理 BaseAgent 实例的注册与查找。
"""

from __future__ import annotations

from .base_agent import BaseAgent


class AgentRegistry:
    """Agent 注册表"""

    def __init__(self) -> None:
        self._agents: dict[str, BaseAgent] = {}

    def get(self, agent_id: str) -> BaseAgent:
        if agent_id not in self._agents:
            raise KeyError(agent_id)
        return self._agents[agent_id]

    def register(self, agent_id: str, agent: BaseAgent) -> None:
        self._agents[agent_id] = agent

    def list_ids(self) -> list[str]:
        return list(self._agents.keys())
