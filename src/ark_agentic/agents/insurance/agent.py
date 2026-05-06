"""
保险智能体 — BaseAgent 子类。

环境变量:
    SESSIONS_DIR: 会话持久化基础目录（默认 data/ark_sessions）
    MEMORY_DIR:   Memory 数据基础目录（默认 data/ark_memory）
"""

from __future__ import annotations

import logging

from ark_agentic import BaseAgent
from ark_agentic.core.flow.callbacks import FlowCallbacks
from ark_agentic.core.runtime.callbacks import RunnerCallbacks

from .tools import create_insurance_tools

logger = logging.getLogger(__name__)

_INSURANCE_PROTOCOL = """\
### 工具调用
- 调用工具时只生成 tool_call，不要附带额外文本

### 输出风格
- 对敏感操作给出风险提示
- render_a2ui 卡片已向用户展示完整数据，后续文字回复禁止重复卡片中的金额、渠道、保单号。卡片后仅需一句简短引导（≤25字）"""


class InsuranceAgent(BaseAgent):
    """保险智能体"""

    agent_id = "insurance"
    agent_name = "保险智能助手"
    agent_description = "专业的保险咨询和业务处理助手。"
    system_protocol = _INSURANCE_PROTOCOL
    enable_subtasks = True

    def build_tools(self):
        return create_insurance_tools(sessions_dir=self.sessions_dir)

    def build_callbacks(self) -> RunnerCallbacks | None:
        # FlowCallbacks instance is constructed for parity with the
        # previous wiring; the inject/persist hooks remain commented out
        # — restoring them is a per-feature decision, not part of this
        # base-class migration.
        FlowCallbacks(sessions_dir=self.sessions_dir)
        return RunnerCallbacks()
