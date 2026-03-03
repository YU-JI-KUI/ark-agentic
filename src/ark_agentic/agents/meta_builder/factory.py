"""
MetaBuilder Agent 工厂

提供 create_meta_builder_from_env() 工厂函数，
对齐框架中 create_insurance_agent_from_env() 等既有约定。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from langchain_core.language_models.chat_models import BaseChatModel

from ark_agentic.core.compaction import CompactionConfig
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
    sessions_dir: str | Path | None = None,
) -> AgentRunner:
    """创建 MetaBuilderAgent 实例。

    Args:
        llm: LLM 实例；若为 None，从环境变量按与其他 Agent 相同的方式初始化。
        sessions_dir: 会话持久化目录；未传时用 SESSIONS_DIR 或 data/ark_sessions/meta_builder。

    Returns:
        配置好的 AgentRunner，agent_id 应注册为 "meta_builder"。
    """
    if llm is None:
        from ark_agentic.core.llm import create_chat_model, PAModel
        provider = os.getenv("LLM_PROVIDER", "pa")
        if provider == "pa":
            pa_model_str = os.getenv("PA_MODEL", "PA-SX-80B")
            try:
                pa_model = PAModel(pa_model_str)
            except ValueError:
                pa_model = PAModel.PA_SX_80B
            llm = create_chat_model(model=pa_model)
            logger.info("MetaBuilder using PA Internal LLM: %s", pa_model.value)
        else:
            api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("LLM_API_KEY")
            base_url = os.getenv("LLM_BASE_URL")
            if not api_key:
                raise ValueError(
                    "MetaBuilder LLM requires LLM_PROVIDER=pa or DEEPSEEK_API_KEY env."
                )
            llm = create_chat_model(
                model="deepseek-chat" if provider == "deepseek" else provider,
                api_key=api_key,
                base_url=base_url,
            )
            logger.info("MetaBuilder using %s LLM", provider)

    # 工具注册（方案 A：3 个复合工具，覆盖 Agent/Skill/Tool 全部能力）
    tool_registry = ToolRegistry()
    tool_registry.register(ManageAgentsTool())
    tool_registry.register(ManageSkillsTool())
    tool_registry.register(ManageToolsTool())

    # Session 管理：优先使用调用方传入的 sessions_dir（app 按 agent_id 隔离）
    if sessions_dir is None:
        base = Path(os.getenv("SESSIONS_DIR") or "data/ark_sessions")
        sessions_dir = base / "meta_builder"
    sessions_dir = Path(sessions_dir)
    sessions_dir.mkdir(parents=True, exist_ok=True)

    session_manager = SessionManager(
        compaction_config=CompactionConfig(context_window=16000, preserve_recent=4),
        sessions_dir=sessions_dir,
        enable_persistence=True,
    )

    # Skill 加载（加载内置 MetaBuilder Guide）
    skill_config = SkillConfig(
        skill_directories=[str(_SKILLS_DIR)],
        agent_id="meta_builder",
        enable_eligibility_check=False,
        default_load_mode=SkillLoadMode.full,
    )
    skill_loader = SkillLoader(skill_config)
    try:
        skill_loader.load_from_directories()
        logger.info("MetaBuilder loaded %d skills", len(skill_loader.list_skills()))
    except Exception as e:
        logger.warning("MetaBuilder skill load failed: %s", e)

    # Runner 配置
    runner_config = RunnerConfig(
        temperature=0.3,  # 构建任务偏低温，确保工具调用精准
        max_tokens=4096,
        max_turns=8,
        enable_streaming=True,
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
