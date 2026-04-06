"""
证券资产管理 Agent

提供证券智能体的构建与配置。路径完全由环境变量控制。

环境变量:
    SESSIONS_DIR: 会话持久化基础目录（默认 data/ark_sessions）
    MEMORY_DIR: Memory 数据基础目录（默认 data/ark_memory）
"""

from __future__ import annotations

import logging
from pathlib import Path

from langchain_core.language_models.chat_models import BaseChatModel

from ark_agentic.core.callbacks import CallbackContext, CallbackResult, RunnerCallbacks
from ark_agentic.core.compaction import CompactionConfig
from ark_agentic.core.memory.manager import build_memory_manager
from ark_agentic.core.paths import get_memory_base_dir, prepare_agent_data_dir
from ark_agentic.core.prompt.builder import PromptConfig
from ark_agentic.core.runner import AgentRunner, RunnerConfig
from ark_agentic.core.session import SessionManager
from ark_agentic.core.skills.base import SkillConfig
from ark_agentic.core.skills.loader import SkillLoader
from ark_agentic.core.tools.registry import ToolRegistry
from ark_agentic.core.types import SkillLoadMode

from ark_agentic.core.tools.citations import RecordCitationsTool
from ark_agentic.core.validation import EntityTrie, create_citation_validation_hook

from .tools import create_securities_tools
from .validation import CITE_SYSTEM_INSTRUCTION, _SECURITIES_TOOL_KEYS

_SKILLS_DIR = Path(__file__).parent / "skills"


def create_securities_agent(
    llm: BaseChatModel | None = None,
    *,
    enable_memory: bool = False,
) -> AgentRunner:
    """创建证券资产管理 Agent

    Args:
        llm: LLM 实例；None 时从环境变量初始化
        enable_memory: 是否启用 Memory 系统；路径由 MEMORY_DIR 环境变量控制
    """
    if llm is None:
        from ark_agentic.core.llm import create_chat_model_from_env

        llm = create_chat_model_from_env()

    sessions_dir = prepare_agent_data_dir("securities")

    memory_dir: Path | None = None
    if enable_memory:
        memory_dir = get_memory_base_dir() / "securities"

    _STOCKS_CSV = Path(__file__).parent / "mock_data" / "stocks" / "a_shares_seed.csv"

    _trie = EntityTrie()
    _trie.load_from_csv(_STOCKS_CSV)
    _citation_hook = create_citation_validation_hook(
        tool_keys=_SECURITIES_TOOL_KEYS,
        entity_trie=_trie,
    )

    tool_registry = ToolRegistry()
    for tool in create_securities_tools():
        tool_registry.register(tool)
    tool_registry.register(RecordCitationsTool())

    from ark_agentic.core.compaction import LLMSummarizer

    summarizer = LLMSummarizer(llm)
    session_manager = SessionManager(
        sessions_dir=sessions_dir,
        compaction_config=CompactionConfig(
            context_window=128000,
            preserve_recent=4,
        ),
        summarizer=summarizer,
    )

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
        pass

    runner_config = RunnerConfig(
        max_tokens=4096,
        max_turns=10,
        prompt_config=PromptConfig(
            agent_name="证券资产管理助手",
            agent_description="专业的证券资产查询与分析助手",
            custom_instructions=CITE_SYSTEM_INSTRUCTION,
        ),
        skill_config=skill_config,
    )

    memory_manager = (
        build_memory_manager(memory_dir) if memory_dir is not None else None
    )

    from .tools.service.param_mapping import enrich_securities_context

    async def _enrich_context(ctx: CallbackContext) -> CallbackResult | None:
        return CallbackResult(
            context_updates=enrich_securities_context(ctx.input_context),
        )

    return AgentRunner(
        llm=llm,
        tool_registry=tool_registry,
        session_manager=session_manager,
        skill_loader=skill_loader,
        config=runner_config,
        memory_manager=memory_manager,
        callbacks=RunnerCallbacks(
            before_agent=[_enrich_context],
            before_complete=[_citation_hook],
        ),
    )
