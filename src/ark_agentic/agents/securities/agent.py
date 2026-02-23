"""
证券资产管理 Agent

提供证券账户资产查询、持仓分析、收益查询等功能。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ark_agentic.core.runner import AgentRunner, RunnerConfig
from ark_agentic.core.tools.registry import ToolRegistry
from ark_agentic.core.prompt.builder import PromptConfig
from ark_agentic.core.llm import LLMClientProtocol
from ark_agentic.core.skills.loader import SkillLoader
from ark_agentic.core.skills.base import SkillConfig

from .tools import create_securities_tools

# 技能目录
_SKILLS_DIR = Path(__file__).parent / "skills"


# Agent 系统提示词
SECURITIES_AGENT_PROMPT = """你是一个专业的证券资产管理助手，帮助用户查询和分析证券账户信息。
"""


def create_securities_agent(
    llm_client: LLMClientProtocol,
    sessions_dir: str | Path | None = None,
    enable_persistence: bool = False,
) -> AgentRunner:
    """
    创建证券资产管理 Agent
    
    Args:
        llm_client: LLM 客户端
        sessions_dir: 会话持久化目录
        enable_persistence: 是否启用会话持久化
    
    Returns:
        配置好的 AgentRunner 实例
    """
    # 创建工具注册表
    tool_registry = ToolRegistry()
    
    # 注册所有证券工具
    for tool in create_securities_tools():
        tool_registry.register(tool)
    
    # 创建 Prompt 配置
    prompt_config = PromptConfig(
        agent_name="证券资产管理助手",
        agent_description="专业的证券资产查询与分析助手",
        # custom_instructions=SECURITIES_AGENT_PROMPT,
    )
    
    # 创建 Runner 配置
    runner_config = RunnerConfig(
        prompt_config=prompt_config,
    )
    
    # 创建技能加载器
    skill_config = SkillConfig(
        skill_directories=[str(_SKILLS_DIR)],
        enable_eligibility_check=True,
    )
    skill_loader = SkillLoader(skill_config)
    try:
        skill_loader.load_from_directories()
    except Exception:
        pass  # 忽略加载错误，确保 Agent 能启动

    # 创建并返回 AgentRunner
    return AgentRunner(
        llm_client=llm_client,
        tool_registry=tool_registry,
        skill_loader=skill_loader,
        config=runner_config,
    )
