"""Agentic Native TaskFlow — 基于 Hook 驱动的流程编排框架。

核心组件:
  BaseFlowEvaluator   — 流程评估器基类（ABC，由 Hook 自动驱动）
  StageDefinition     — 阶段定义（Pydantic 校验 + reference 绑定 + checkpoint + task_name_template）
  FlowEvaluatorRegistry — 全局单例注册表（skill_name → evaluator 实例，支持 namespace 别名）
  TaskRegistry        — active_tasks.json 读写（持久化 + TTL 清理 + 短 flow_id 生成）
  FlowCallbacks       — 三个 Hook（before_model_flow_eval / after_tool_auto_commit / persist_flow_context）
"""

from .base_evaluator import BaseFlowEvaluator, FlowEvaluatorRegistry, StageDefinition
from .task_registry import TaskRegistry

__all__ = [
    "BaseFlowEvaluator",
    "FlowEvaluatorRegistry",
    "StageDefinition",
    "TaskRegistry",
]
