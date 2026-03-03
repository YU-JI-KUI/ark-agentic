"""
Agent 注册表

管理 AgentRunner 实例的注册与查找。
从 app.py 提取，供 api/ 和 studio/ 共享使用。
"""

from __future__ import annotations

from ark_agentic.core.runner import AgentRunner


class AgentRegistry:
    """Agent 注册表"""

    def __init__(self) -> None:
        self._agents: dict[str, AgentRunner] = {}

    def get(self, agent_id: str) -> AgentRunner:
        if agent_id not in self._agents:
            raise KeyError(agent_id)
        return self._agents[agent_id]

    def register(self, agent_id: str, agent: AgentRunner) -> None:
        self._agents[agent_id] = agent

    def list_ids(self) -> list[str]:
        return list(self._agents.keys())
