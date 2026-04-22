"""RollbackFlowStageTool — 将流程回退到指定 checkpoint 阶段。

调用条件：用户明确希望修改已完成阶段的内容（如更换方案、重新查询）。

工作流程（LLM 侧）：
  1. 从 evaluator 响应的 available_checkpoints 中找到匹配用户意图的目标阶段
  2. 向用户确认回退操作（单一匹配直接确认，多个候选展示列表让用户选择）
  3. 用户确认后调用本工具 rollback_flow_stage(stage_id=<target>)
  4. 工具自动清除目标阶段及后续所有阶段的数据
  5. 再次调用 evaluator，从目标阶段重新执行
"""

from __future__ import annotations

import logging
from typing import Any

from ..tools.base import AgentTool, ToolParameter
from ..types import AgentToolResult, ToolCall, ToolResultType
from .base_evaluator import FlowEvaluatorRegistry

logger = logging.getLogger(__name__)


class RollbackFlowStageTool(AgentTool):
    """将流程回退到指定 checkpoint 阶段，清除目标及后续所有阶段的已完成数据。"""

    name = "rollback_flow_stage"
    description = (
        "将流程回退到指定的 checkpoint 阶段，清除目标阶段及其后续所有阶段的数据。"
        "只能回退到已完成的 checkpoint 阶段（从 available_checkpoints 中获取）。"
    )
    parameters = [
        ToolParameter(
            name="stage_id",
            type="string",
            required=True,
            description=(
                "要回退到的 checkpoint 阶段 ID。"
                "必须从 available_checkpoints 列表中取值，"
                "并已得到用户明确确认。"
            ),
        ),
    ]

    async def execute(
        self, tool_call: ToolCall, context: dict[str, Any] | None = None
    ) -> AgentToolResult:
        ctx = context or {}
        target_stage_id = (tool_call.arguments.get("stage_id") or "").strip()
        if not target_stage_id:
            return AgentToolResult.error_result(tool_call.id, "stage_id 不能为空")

        flow_ctx: dict[str, Any] = dict(ctx.get("_flow_context") or {})
        skill_name = flow_ctx.get("skill_name", "")
        if not skill_name:
            return AgentToolResult.error_result(
                tool_call.id, "未检测到活跃流程，请先调用 flow evaluator 初始化流程。"
            )

        evaluator = FlowEvaluatorRegistry.get(skill_name)
        if not evaluator:
            return AgentToolResult.error_result(
                tool_call.id, f"未找到 skill '{skill_name}' 对应的 evaluator。"
            )

        # 校验目标阶段存在且为 checkpoint
        target_stage = next((s for s in evaluator.stages if s.id == target_stage_id), None)
        if not target_stage:
            available = [s.id for s in evaluator.stages if s.checkpoint]
            return AgentToolResult.error_result(
                tool_call.id,
                f"阶段 '{target_stage_id}' 不存在。可用的 checkpoint 阶段：{available}",
            )
        if not target_stage.checkpoint:
            checkpoints = [s.id for s in evaluator.stages if s.checkpoint]
            return AgentToolResult.error_result(
                tool_call.id,
                f"阶段 '{target_stage.name}' 不是 checkpoint 阶段，无法回退。"
                f"可用的 checkpoint 阶段：{checkpoints}",
            )

        # 校验目标阶段已在 checkpoints 历史中（即已完成过）
        recorded_checkpoints: list[dict[str, Any]] = list(flow_ctx.get("checkpoints") or [])
        if not any(c.get("stage_id") == target_stage_id for c in recorded_checkpoints):
            return AgentToolResult.error_result(
                tool_call.id,
                f"阶段 '{target_stage.name}' 尚未完成，无需回退。",
            )

        # 找到目标阶段在 stages 列表中的索引，清除目标及后续所有阶段
        stage_ids = [s.id for s in evaluator.stages]
        target_idx = stage_ids.index(target_stage_id)
        stages_to_clear = evaluator.stages[target_idx:]

        state_delta: dict[str, Any] = {}
        for stage in stages_to_clear:
            state_delta[f"_flow_context.stage_{stage.id}"] = {}
            state_delta[f"_flow_context.stage_{stage.id}_delta"] = {}

        # 同步移除已清除阶段的 checkpoint 记录
        cleared_ids = {s.id for s in stages_to_clear}
        updated_checkpoints = [
            c for c in recorded_checkpoints if c.get("stage_id") not in cleared_ids
        ]
        state_delta["_flow_context.checkpoints"] = updated_checkpoints

        logger.info(
            "Flow rolled back: skill=%s target=%s cleared=%s",
            skill_name, target_stage_id, [s.id for s in stages_to_clear],
        )

        return AgentToolResult(
            tool_call_id=tool_call.id,
            result_type=ToolResultType.JSON,
            content={
                "status": "rolled_back",
                "target_stage": {"id": target_stage_id, "name": target_stage.name},
                "cleared_stages": [s.id for s in stages_to_clear],
                "message": (
                    f"已回退到【{target_stage.name}】阶段，"
                    f"已清除该阶段及后续 {len(stages_to_clear)} 个阶段的数据。"
                ),
            },
            metadata={"state_delta": state_delta},
        )
