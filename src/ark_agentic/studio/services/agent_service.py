"""
Agent Service — Phase 5 预留接口

Phase 5 的 MetaBuilderAgent 将通过此 Service 动态创建完整的 Agent：
  1. 创建目录结构 (agent.json, skills/, tools/)
  2. 生成默认 SKILL.md 和工具脚手架
  3. 热注册到 AgentRegistry
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class AgentScaffoldSpec:
    """Agent 脚手架规格。

    Attributes:
        name: Agent 显示名称
        description: Agent 功能描述
        skills: 初始技能列表 [{name, description, content}]
        tools: 初始工具列表 [{name, description, parameters}]
        llm_config: LLM 配置 {model, temperature, ...}
    """
    name: str
    description: str = ""
    skills: list[dict[str, str]] = field(default_factory=list)
    tools: list[dict[str, Any]] = field(default_factory=list)
    llm_config: dict[str, Any] = field(default_factory=dict)


def scaffold_agent(
    agents_root: Path,
    spec: AgentScaffoldSpec,
) -> Path:
    """根据 spec 创建完整的 Agent 目录结构。

    Phase 5 实现时，此函数将：
    1. 创建 agents/{slug}/ 目录
    2. 生成 agent.json (name, description, llm_config)
    3. 创建 skills/ 目录，遍历 spec.skills 调用 skill_service.create_skill
    4. 创建 tools/ 目录，遍历 spec.tools 调用 tool_service.scaffold_tool
    5. 返回创建的 Agent 根目录 Path

    Args:
        agents_root: Agent 根目录
        spec: Agent 脚手架规格

    Returns:
        创建的 Agent 目录 Path

    Raises:
        NotImplementedError: Phase 5 待实现
    """
    # TODO: Phase 5 实现
    raise NotImplementedError("Agent scaffold will be implemented in Phase 5")
