"""Agentic Native TaskFlow — 基于 Hook 驱动的流程编排框架。

核心组件:
  BaseFlowEvaluator   — 流程评估器基类（ABC，由 Hook 自动驱动）
  StageDefinition     — 阶段定义（Pydantic 校验 + reference 绑定 + checkpoint + task_name_template）
  FlowEvaluatorRegistry — 全局单例注册表（skill_name → evaluator 实例，支持 namespace 别名）
  FieldDefinition     — 阶段字段定义（统一声明抽取策略）
  FieldStatus         — 单字段评估状态
  StageEvaluation     — 单阶段评估结果
  FlowEvalResult      — 完整评估结果
  FlowCallbacks       — 两个 Hook（before_model_flow_eval / persist_flow_context）
"""

from .base_evaluator import (
    BaseFlowEvaluator,
    FieldDefinition,
    FieldSource,
    FieldStatus,
    FlowEvalResult,
    FlowEvaluatorRegistry,
    StageDefinition,
    StageEvaluation,
)

__all__ = [
    "BaseFlowEvaluator",
    "FieldDefinition",
    "FieldSource",
    "FieldStatus",
    "FlowEvalResult",
    "FlowEvaluatorRegistry",
    "StageDefinition",
    "StageEvaluation",
]
