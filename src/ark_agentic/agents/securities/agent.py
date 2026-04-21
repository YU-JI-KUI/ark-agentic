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

from ark_agentic.core.callbacks import CallbackContext, CallbackEvent, CallbackResult, HookAction, RunnerCallbacks
from ark_agentic.core.compaction import CompactionConfig
from ark_agentic.core.memory.manager import build_memory_manager
from ark_agentic.observability import (
    apply_observability_bindings,
    build_observability_bindings,
)
from ark_agentic.services.jobs import (
    apply_proactive_job_bindings,
    build_proactive_job_bindings,
)
from ark_agentic.core.paths import get_memory_base_dir, prepare_agent_data_dir
from ark_agentic.core.prompt.builder import PromptConfig
from ark_agentic.core.runner import AgentRunner, RunnerConfig
from ark_agentic.core.session import SessionManager
from ark_agentic.core.skills.base import SkillConfig
from ark_agentic.core.skills.loader import SkillLoader
from ark_agentic.core.tools.registry import ToolRegistry
from ark_agentic.core.types import SkillLoadMode
from ark_agentic.core.validation import EntityTrie, create_citation_validation_hook

from .tools import create_securities_tools
from .validation import VALIDATION_SYSTEM_INSTRUCTION

_SKILLS_DIR = Path(__file__).parent / "skills"


def create_securities_agent(
    llm: BaseChatModel | None = None,
    *,
    enable_memory: bool = False,
    enable_dream: bool = True,
    proactive_cron: str = "0 9 * * 1-5",
) -> AgentRunner:
    """创建证券资产管理 Agent

    Args:
        llm: LLM 实例；None 时从环境变量初始化
        enable_memory: 是否启用 Memory 系统；路径由 MEMORY_DIR 环境变量控制
        enable_dream: 是否启用 Dream 后台蒸馏（需 enable_memory=True 才有效）
        proactive_cron: 主动服务 Job 的触发时间（cron 表达式），默认工作日早 9 点。
            常用示例：
              "0 9 * * 1-5"   每个工作日早 9 点（默认）
              "0 8,12 * * *"  每天早 8 点和中午 12 点
              "*/30 9-15 * * 1-5"  工作日 9-15 点每 30 分钟
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
    _citation_hook = create_citation_validation_hook(entity_trie=_trie)

    tool_registry = ToolRegistry()
    for tool in create_securities_tools():
        tool_registry.register(tool)

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
        load_mode=SkillLoadMode.dynamic,
    )
    skill_loader = SkillLoader(skill_config)
    try:
        skill_loader.load_from_directories()
    except Exception:
        pass

    runner_config = RunnerConfig(
        max_tokens=4096,
        max_turns=10,
        enable_dream=enable_dream,
        prompt_config=PromptConfig(
            agent_name="证券资产管理助手",
            agent_description="专业的证券资产查询与分析助手",
            custom_instructions=VALIDATION_SYSTEM_INSTRUCTION,
        ),
        skill_config=skill_config,
    )

    memory_manager = (
        build_memory_manager(memory_dir) if memory_dir is not None else None
    )

    from .tools.service.param_mapping import enrich_securities_context, _get_context_value

    async def _enrich_context(ctx: CallbackContext) -> CallbackResult | None:
        return CallbackResult(
            context_updates=enrich_securities_context(ctx.input_context),
        )

    async def _auth_check(ctx: CallbackContext) -> CallbackResult | None:
        login_flag = _get_context_value(ctx.input_context, "loginflag")
        if str(login_flag) != "1":
            return None
        account_type = _get_context_value(ctx.input_context, "account_type", "normal")
        type_code = "1" if account_type == "margin" else "2"
        return CallbackResult(
            action=HookAction.ABORT,
            response=AgentMessage.assistant("需要进行证券账户登录才能访问该服务。"),
            event=CallbackEvent(
                type="ui_component",
                data={
                    "template": "common_login",
                    "body": {
                        "actionAuth": "Z",
                        "type": type_code,
                    },
                },
            ),
        )

    existing_callbacks = RunnerCallbacks(
        before_agent=[_enrich_context, _auth_check],
        before_loop_end=[_citation_hook],
    )
    observability = build_observability_bindings(
        agent_id=skill_config.agent_id,
        agent_name=runner_config.prompt_config.agent_name,
        callbacks=existing_callbacks,
    )

    # 构建证券专属主动服务 Job（memory 启用时），随 runner 一起交给框架调度
    proactive_job = None
    if memory_manager is not None:
        assert llm is not None  # llm 在函数入口已初始化，此处不可能为 None
        from .proactive_job import SecuritiesProactiveJob
        _llm = llm  # 收窄类型：BaseChatModel | None → BaseChatModel
        proactive_job = SecuritiesProactiveJob(
            job_id="proactive_service_securities",
            llm_factory=lambda: _llm,
            tool_registry=tool_registry,
            memory_manager=memory_manager,
            cron=proactive_cron,
        )

    runner = AgentRunner(
        llm=llm,
        tool_registry=tool_registry,
        session_manager=session_manager,
        skill_loader=skill_loader,
        config=runner_config,
        memory_manager=memory_manager,
        callbacks=observability.callbacks,
    )
    apply_observability_bindings(runner, observability)
    apply_proactive_job_bindings(
        runner,
        build_proactive_job_bindings(job=proactive_job),
    )
    return runner
