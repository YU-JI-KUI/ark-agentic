"""
list_agents Tool — 列出当前所有 Agent
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from ark_agentic.core.tools.base import AgentTool
from ark_agentic.core.types import AgentToolResult, ToolCall
from ark_agentic.core.utils.env import get_agents_root
from ark_agentic.studio.services.agent_service import list_agents as svc_list_agents

logger = logging.getLogger(__name__)



class ListAgentsTool(AgentTool):
    """列出所有已部署的 Agent，包含名称、ID 和描述。"""

    name = "list_agents"
    description = "列出当前 Studio 中所有可管理的 Agent（名称、ID 和描述）。在创建新 Agent 前建议先调用此工具了解全局情况。"
    parameters = []

    async def execute(self, tool_call: ToolCall, context: dict[str, Any] | None = None) -> AgentToolResult:
        try:
            agents = svc_list_agents(get_agents_root(__file__))
            if not agents:
                return AgentToolResult.text_result(tool_call.id, "当前没有任何 Agent。")
            lines = [f"共找到 {len(agents)} 个 Agent："]
            for a in agents:
                lines.append(f"- **{a.name}** (id: `{a.id}`): {a.description or '无描述'}")
            return AgentToolResult.text_result(tool_call.id, "\n".join(lines))
        except Exception as e:
            logger.exception("list_agents failed")
            return AgentToolResult.text_result(tool_call.id, f"列出 Agent 失败：{e}")
