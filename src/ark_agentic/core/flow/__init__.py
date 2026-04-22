"""Agentic Native TaskFlow — 基于资源引用与状态工具的流程编排框架。

核心组件:
  BaseFlowEvaluator   — 流程评估器基类（确定性状态机）
  StageDefinition     — 阶段定义（Pydantic 校验 + reference 绑定）
  FlowEvaluatorRegistry — 全局单例注册表（skill_name → evaluator 实例）
  TaskRegistry        — active_tasks.json 读写（持久化 + TTL 清理）
  FlowCallbacks       — persist_flow_context after_agent hook（待恢复任务检测已移入 BaseFlowEvaluator.execute()）
"""

from .base_evaluator import BaseFlowEvaluator, FlowEvaluatorRegistry, StageDefinition
from .task_registry import TaskRegistry

__all__ = [
    "BaseFlowEvaluator",
    "FlowEvaluatorRegistry",
    "StageDefinition",
    "TaskRegistry",
]
