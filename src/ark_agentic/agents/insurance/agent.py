"""
保险智能体 — BaseAgent 子类。

环境变量:
    SESSIONS_DIR: 会话持久化基础目录（默认 data/ark_sessions）
    MEMORY_DIR:   Memory 数据基础目录（默认 data/ark_memory）
"""

from __future__ import annotations

import logging

from ark_agentic import BaseAgent
from ark_agentic.agents.insurance.tools.flow_evaluator import withdrawal_flow_evaluator
from ark_agentic.core.citation import create_cite_annotation_hook
from ark_agentic.core.flow.base_evaluator import FlowEvaluatorRegistry
from ark_agentic.core.flow.callbacks import FlowCallbacks
from ark_agentic.core.runtime.callbacks import RunnerCallbacks
from ark_agentic.core.types import SkillLoadMode

from .tools import create_insurance_tools

logger = logging.getLogger(__name__)

_INSURANCE_PROTOCOL = """\
### 工具调用
- 调用工具时只生成 tool_call，不要附带额外文本

### 输出风格
- 对敏感操作给出风险提示
- render_a2ui 卡片已向用户展示完整数据，后续文字回复禁止重复卡片中的金额、渠道、保单号。卡片后仅需一句简短引导（≤25字）"""


# Side-effect: register the withdrawal flow evaluator at module import so the
# stage-aware skill router can find it. Idempotent — registry is per-process.
FlowEvaluatorRegistry.register(withdrawal_flow_evaluator, namespace="insurance")


class InsuranceAgent(BaseAgent):
    """保险智能体"""

    agent_id = "insurance"
    agent_name = "保险智能助手"
    agent_description = "专业的保险咨询和业务处理助手。"
    system_protocol = _INSURANCE_PROTOCOL
    enable_subtasks = True
    skill_load_mode = SkillLoadMode.full

    def build_tools(self):
        return create_insurance_tools(sessions_dir=self.sessions_dir)

    def build_callbacks(self) -> RunnerCallbacks | None:
        flow_callbacks = FlowCallbacks(
            sessions_dir=self.sessions_dir,
            skill_loader=self.skill_loader,
        )
        cite_hook = create_cite_annotation_hook(tool_registry=self.tool_registry)
        return RunnerCallbacks(
            before_model=[flow_callbacks.before_model_flow_eval],
            before_tool=[flow_callbacks.before_tool_stage_guard],
            before_loop_end=[cite_hook],
            after_agent=[flow_callbacks.persist_flow_context],
        )
