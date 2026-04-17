"""Agentic Native TaskFlow — 基于资源引用与状态工具的流程编排框架。

核心组件:
  BaseFlowEvaluator   — 流程评估器基类（AgentTool 子类，确定性状态机）
  StageDefinition     — 阶段定义（Pydantic 校验 + reference 绑定）
  FlowEvaluatorRegistry — 全局单例注册表（skill_name → evaluator 实例）
  TaskRegistry        — active_tasks.json 读写（持久化 + TTL 清理）
  persist_flow_context / inject_flow_hint — after_agent / before_agent hook 实现
"""

from .base_evaluator import BaseFlowEvaluator, FlowEvaluatorRegistry, StageDefinition
from .task_registry import TaskRegistry

__all__ = [
    "BaseFlowEvaluator",
    "FlowEvaluatorRegistry",
    "StageDefinition",
    "TaskRegistry",
]
