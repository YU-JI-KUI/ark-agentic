"""
MetaBuilder Agent 工厂

提供 create_meta_builder_from_env() 工厂函数，
对齐框架中 create_insurance_agent() 等既有约定。
"""

from __future__ import annotations

import logging
from pathlib import Path

from langchain_core.language_models.chat_models import BaseChatModel

from ark_agentic.core.compaction import CompactionConfig
from ark_agentic.core.llm.sampling import SamplingConfig
from ark_agentic.core.paths import prepare_agent_data_dir
from ark_agentic.core.prompt.builder import PromptConfig
from ark_agentic.core.runner import AgentRunner, RunnerConfig
from ark_agentic.core.session import SessionManager
from ark_agentic.core.skills.base import SkillConfig
from ark_agentic.core.skills.loader import SkillLoader
from ark_agentic.core.tools.registry import ToolRegistry
from ark_agentic.core.types import SkillLoadMode

from .tools.manage_agents import ManageAgentsTool
from .tools.manage_skills import ManageSkillsTool
from .tools.manage_tools import ManageToolsTool

logger = logging.getLogger(__name__)

_AGENT_DIR = Path(__file__).resolve().parent
_SKILLS_DIR = _AGENT_DIR / "skills"


def create_meta_builder_from_env(
    llm: BaseChatModel | None = None,
) -> AgentRunner:
    """创建 MetaBuilderAgent 实例。

    Args:
        llm: LLM 实例；若为 None，从环境变量按与其他 Agent 相同的方式初始化。

    Returns:
        配置好的 AgentRunner，agent_id 应注册为 "meta_builder"。
    """
    if llm is None:
        from ark_agentic.core.llm import create_chat_model_from_env
        llm = create_chat_model_from_env()

    # 工具注册（方案 A：3 个复合工具，覆盖 Agent/Skill/Tool 全部能力）
    tool_registry = ToolRegistry()
    tool_registry.register(ManageAgentsTool())
    tool_registry.register(ManageSkillsTool())
    tool_registry.register(ManageToolsTool())

    sessions_dir = prepare_agent_data_dir("meta_builder")

    session_manager = SessionManager(
        sessions_dir,
        compaction_config=CompactionConfig(context_window=64000, preserve_recent=4),
    )

    # Skill 加载（加载内置 MetaBuilder Guide）
    skill_config = SkillConfig(
        skill_directories=[str(_SKILLS_DIR)],
        agent_id="meta_builder",
        enable_eligibility_check=False,
        load_mode=SkillLoadMode.full,
    )
    skill_loader = SkillLoader(skill_config)
    try:
        skill_loader.load_from_directories()
        logger.info("MetaBuilder loaded %d skills", len(skill_loader.list_skills()))
    except Exception as e:
        logger.warning("MetaBuilder skill load failed: %s", e)

    # Runner 配置
    runner_config = RunnerConfig(
        # 构建任务：低温 + 精准工具调用（适度提高 temperature 以避免过度确定性导致输出重复）
        sampling=SamplingConfig.for_chat(temperature=0.3),
        max_turns=8,
        prompt_config=PromptConfig(
            agent_name="Ark-Agentic Meta-Agent",
            agent_description=(
                "你是一个 AI 构建助手，帮助开发者通过自然语言创建和管理 Agent、Skill 和 Tool。"
                "你拥有直接操作文件系统的工具，可以立即将创建结果持久化到磁盘。"
            ),
        ),
        skill_config=skill_config,
    )

    runner = AgentRunner(
        llm=llm,
        tool_registry=tool_registry,
        session_manager=session_manager,
        skill_loader=skill_loader,
        config=runner_config,
    )

    return runner
