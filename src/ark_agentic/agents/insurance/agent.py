"""
保险智能体

提供保险智能体的构建与配置。路径完全由环境变量控制。

环境变量:
    SESSIONS_DIR: 会话持久化基础目录（默认 data/ark_sessions）
    MEMORY_DIR: Memory 数据基础目录（默认 data/ark_memory）
"""

from __future__ import annotations

import logging
from pathlib import Path

from langchain_core.language_models.chat_models import BaseChatModel

# from ark_agentic.agents.insurance.guard import InsuranceIntakeGuard, make_before_agent_callback  # DEBUG: 暂时禁用准入拦截
from ark_agentic.agents.insurance.tools import create_insurance_tools
from ark_agentic.core.compaction import CompactionConfig
from ark_agentic.core.guardrails import create_guardrails_callbacks
from ark_agentic.core.memory.manager import build_memory_manager
from ark_agentic.core.paths import get_memory_base_dir, prepare_agent_data_dir
from ark_agentic.core.prompt.builder import PromptConfig
from ark_agentic.core.callbacks import RunnerCallbacks, merge_runner_callbacks
from ark_agentic.core.flow.callbacks import FlowCallbacks
from ark_agentic.core.runner import AgentRunner, RunnerConfig
from ark_agentic.core.session import SessionManager
from ark_agentic.core.skills.base import SkillConfig
from ark_agentic.core.skills.loader import SkillLoader
from ark_agentic.core.tools.registry import ToolRegistry
from ark_agentic.core.types import SkillLoadMode

logger = logging.getLogger(__name__)

_AGENT_DIR = Path(__file__).resolve().parent
_SKILLS_DIR = _AGENT_DIR / "skills"

_INSURANCE_PROTOCOL = """\
### 工具调用
- 调用工具时只生成 tool_call，不要附带额外文本

### 输出风格
- 对敏感操作给出风险提示"""


def create_insurance_agent(
    llm: BaseChatModel | None = None,
    *,
    enable_memory: bool = False,
    enable_thinking_tags: bool = False,
    proactive_cron: str = "26 23 * * *",
) -> AgentRunner:
    """创建保险智能体

    Args:
        llm: LLM 实例；None 时从环境变量初始化
        enable_memory: 是否启用 Memory 系统；路径由 MEMORY_DIR 环境变量控制
        enable_thinking_tags: 是否启用 <think>/<final> 标签解析
    """
    if llm is None:
        from ark_agentic.core.llm import create_chat_model_from_env
        llm = create_chat_model_from_env()

    sessions_dir = prepare_agent_data_dir("insurance")

    memory_dir: Path | None = None
    if enable_memory:
        memory_dir = get_memory_base_dir() / "insurance"

    tool_registry = ToolRegistry()
    tool_registry.register_all(create_insurance_tools(sessions_dir=sessions_dir))

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
        agent_id="insurance",
        enable_eligibility_check=True,
        load_mode=SkillLoadMode.full,
    )
    skill_loader = SkillLoader(skill_config)
    try:
        skill_loader.load_from_directories()
        logger.info(f"Loaded {len(skill_loader.list_skills())} skills")
    except Exception as e:
        logger.warning(f"Failed to load skills: {e}")

    memory_manager = build_memory_manager(memory_dir) if memory_dir is not None else None

    runner_config = RunnerConfig(
        max_tokens=4096,
        max_turns=10,
        enable_thinking_tags=enable_thinking_tags,
        enable_subtasks=True,
        prompt_config=PromptConfig(
            agent_name="保险智能助手",
            agent_description="专业的保险咨询和业务处理助手。",
            system_protocol=_INSURANCE_PROTOCOL,
        ),
        skill_config=skill_config,
    )

    # 构建保险专属主动服务 Job（memory 启用时），随 runner 一起交给框架调度
    proactive_job = None
    if memory_manager is not None:
        assert llm is not None  # llm 在函数入口已初始化，此处不可能为 None
        from .proactive_job import InsuranceProactiveJob
        _llm = llm  # 收窄类型：BaseChatModel | None → BaseChatModel
        proactive_job = InsuranceProactiveJob(
            job_id="proactive_service_insurance",
            llm_factory=lambda: _llm,
            tool_registry=tool_registry,
            memory_manager=memory_manager,
            cron=proactive_cron,
        )

    flow_callbacks = FlowCallbacks(sessions_dir=sessions_dir)
    callbacks = merge_runner_callbacks(
        RunnerCallbacks(
            # before_agent=[make_before_agent_callback(InsuranceIntakeGuard(llm))],  # DEBUG: 暂时禁用准入拦截
        ),
        RunnerCallbacks(
            after_agent=[flow_callbacks.persist_flow_context],
        ),
    )

    return AgentRunner(
        llm=llm,
        tool_registry=tool_registry,
        session_manager=session_manager,
        skill_loader=skill_loader,
        config=runner_config,
        memory_manager=memory_manager,
        callbacks=callbacks,
        proactive_job=proactive_job,
    )
