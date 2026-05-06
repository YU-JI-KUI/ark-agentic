"""
保险智能体

创建并配置保险 AgentRunner。路径完全由环境变量控制。

环境变量:
    SESSIONS_DIR: 会话持久化基础目录（默认 data/ark_sessions）
    MEMORY_DIR:   Memory 数据基础目录（默认 data/ark_memory）
"""

from __future__ import annotations

import logging
from pathlib import Path

from langchain_core.language_models.chat_models import BaseChatModel

from ark_agentic.agents.insurance.tools.flow_evaluator import withdrawal_flow_evaluator
from ark_agentic.core.flow.base_evaluator import FlowEvaluatorRegistry
from ark_agentic.core.flow.callbacks import FlowCallbacks
from ark_agentic.core.paths import prepare_agent_data_dir
from ark_agentic.core.runtime.callbacks import RunnerCallbacks, merge_runner_callbacks
from ark_agentic.core.runtime.factory import AgentDef, build_standard_agent
from ark_agentic.core.runtime.runner import AgentRunner
from ark_agentic.core.skills.base import SkillConfig
from ark_agentic.core.skills.loader import SkillLoader
from ark_agentic.core.types import SkillLoadMode

from .tools import create_insurance_tools

logger = logging.getLogger(__name__)

_AGENT_DIR = Path(__file__).resolve().parent

_INSURANCE_PROTOCOL = """\
### 工具调用
- 调用工具时只生成 tool_call，不要附带额外文本

### 输出风格
- 对敏感操作给出风险提示
- render_a2ui 卡片已向用户展示完整数据，后续文字回复禁止重复卡片中的金额、渠道、保单号。卡片后仅需一句简短引导（≤25字）"""

_DEF = AgentDef(
    agent_id="insurance",
    agent_name="保险智能助手",
    agent_description="专业的保险咨询和业务处理助手。",
    system_protocol=_INSURANCE_PROTOCOL,
    enable_subtasks=True,
    skill_load_mode=SkillLoadMode.full,
)


def create_insurance_agent(
    llm: BaseChatModel | None = None,
    *,
    enable_memory: bool = False,
    enable_dream: bool = True,
) -> AgentRunner:
    """创建保险智能体

    Args:
        llm: LLM 实例；None 时从环境变量初始化
        enable_memory: 是否启用 Memory 系统；路径由 MEMORY_DIR 环境变量控制
        enable_dream: 是否启用 Dream 后台蒸馏（需 enable_memory=True 才有效）
    """
    sessions_dir = prepare_agent_data_dir(_DEF.agent_id)

    FlowEvaluatorRegistry.register(withdrawal_flow_evaluator, namespace="insurance")

    skill_config = SkillConfig(
        skill_directories=[str(_AGENT_DIR / "skills")],
        agent_id=_DEF.agent_id,
        enable_eligibility_check=True,
        load_mode=_DEF.skill_load_mode,
    )
    skill_loader = SkillLoader(skill_config)
    try:
        skill_loader.load_from_directories()
        logger.info("Loaded %d insurance skills", len(skill_loader.list_skills()))
    except Exception as exc:
        logger.warning("Failed to load insurance skills: %s", exc)

    flow_callbacks = FlowCallbacks(sessions_dir=sessions_dir, skill_loader=skill_loader)
    callbacks = merge_runner_callbacks(
        RunnerCallbacks(),
        RunnerCallbacks(
            before_model=[flow_callbacks.before_model_flow_eval],
            before_tool=[flow_callbacks.before_tool_stage_guard],
            after_agent=[flow_callbacks.persist_flow_context],
        ),
    )
    return build_standard_agent(
        _DEF,
        skills_dir=_AGENT_DIR / "skills",
        tools=create_insurance_tools(sessions_dir=sessions_dir),
        llm=llm,
        enable_memory=enable_memory,
        enable_dream=enable_dream,
        callbacks=callbacks,
        skill_loader=skill_loader,
    )
