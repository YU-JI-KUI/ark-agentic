"""
证券资产管理 Agent

提供证券账户资产查询、持仓分析、收益查询等功能。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
import tempfile
from typing import Any

from ark_agentic.core.compaction import CompactionConfig
from ark_agentic.core.memory.manager import MemoryConfig, MemoryManager
from ark_agentic.core.runner import AgentRunner, RunnerConfig
from ark_agentic.core.session import SessionManager
from ark_agentic.core.tools.registry import ToolRegistry
from ark_agentic.core.prompt.builder import PromptConfig
from langchain_core.language_models.chat_models import BaseChatModel
from ark_agentic.core.skills.loader import SkillLoader
from ark_agentic.core.skills.base import SkillConfig
from ark_agentic.core.types import SkillLoadMode

from .tools import create_securities_tools

logger = logging.getLogger(__name__)

# 技能目录
_SKILLS_DIR = Path(__file__).parent / "skills"


# Agent 系统提示词
SECURITIES_AGENT_PROMPT = """你是一个专业的证券资产管理助手，帮助用户查询和分析证券账户信息。
"""


def create_securities_agent(
    llm: BaseChatModel,
    sessions_dir: str | Path | None = None,
    enable_persistence: bool = False,
    memory_dir: str | Path | None = None,
    enable_memory: bool = False,
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
    
    from ark_agentic.core.compaction import LLMSummarizer
    summarizer = LLMSummarizer(llm)
    session_manager = SessionManager(
        compaction_config=CompactionConfig(
            context_window=32000,
            preserve_recent=4,
        ),
        sessions_dir=sessions_dir if enable_persistence else None,
        enable_persistence=enable_persistence,
        summarizer=summarizer,
    )
    
    # 创建技能加载器
    skill_config = SkillConfig(
        skill_directories=[str(_SKILLS_DIR)],
        agent_id="securities",
        enable_eligibility_check=True,
        default_load_mode=SkillLoadMode.dynamic,
    )
    skill_loader = SkillLoader(skill_config)
    try:
        skill_loader.load_from_directories()
    except Exception:
        pass  # 忽略加载错误，确保 Agent 能启动

    # 创建 Runner 配置
    runner_config = RunnerConfig(
        temperature=float(os.getenv("DEFAULT_TEMPERATURE", "0.7")),
        max_tokens=4096,
        max_turns=10,
        prompt_config=prompt_config,
        skill_config=skill_config,
    )

    # 4. 可选：创建 MemoryManager
    memory_manager = None
    if enable_memory:
        if memory_dir is None:
            memory_dir = Path(tempfile.gettempdir()) / "ark_memory"
        memory_dir = Path(memory_dir)
        memory_dir.mkdir(parents=True, exist_ok=True)

        # workspace_dir 和 index_dir 都指向 memory_dir，
        # 使得 memory 内容文件（MEMORY.md 等）和 FAISS 索引共存于数据目录
        index_sub = memory_dir / ".index"
        index_sub.mkdir(parents=True, exist_ok=True)

        # 初始化 MEMORY.md（如不存在）
        seed_file = memory_dir / "MEMORY.md"
        if not seed_file.exists():
            seed_file.write_text(
                "# Agent Memory\n\n此文件用于存储跨会话的长期记忆。\n",
                encoding="utf-8",
            )

        memory_config = MemoryConfig(
            workspace_dir=str(memory_dir),
            index_dir=str(index_sub),
        )
        memory_manager = MemoryManager(memory_config)
        logger.info(f"Memory enabled: workspace={memory_dir}, index={index_sub}")
        
    # 创建并返回 AgentRunner
    return AgentRunner(
        llm=llm,
        tool_registry=tool_registry,
        session_manager=session_manager,
        skill_loader=skill_loader,
        config=runner_config,
        memory_manager=memory_manager,
    )
