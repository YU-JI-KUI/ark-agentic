"""CollectUserFieldsTool — 向当前流程阶段提交用户提供的字段。

替代原 CommitFlowStageTool，设计差异：
  - 无 stage_id 参数：从 _flow_context["current_stage"] 自动推断
  - 仅需提供无 state_key 的字段；有 state_key 的字段由 evaluator 自动从 session.state 提取
  - 用户字段写入暂存区 _user_input_{stage_id}，由 evaluate() 统一抽取和提交
"""

from __future__ import annotations

import logging
from typing import Any

from ..tools.base import AgentTool, ToolParameter
from ..types import AgentToolResult, ToolCall
from .base_evaluator import FlowEvaluatorRegistry

logger = logging.getLogger(__name__)


class CollectUserFieldsTool(AgentTool):
    """向当前流程阶段提交用户提供的信息。

    框架自动推断当前阶段（无需 stage_id 参数）。
    LLM 只需提供用户对话中收集到的字段（无 state_key 的字段），
    这些字段会被写入暂存区 _user_input_{stage_id}，
    由下一轮 evaluate() 统一抽取、校验并提交。
    """

    name = "collect_user_fields"
    description = (
        "向当前流程阶段提交用户提供的信息。"
        "只需提供用户输入的字段（无 state_key 的字段）；"
        "有 state_key 的字段由框架自动从 session.state 提取。"
        "提交成功后框架将在下一轮自动评估并推进到下一阶段。"
    )
    group = "flow"

    parameters = [
        ToolParameter(
            name="fields",
            type="object",
            description=(
                "当前阶段需要用户提供的字段键值对。"
                "只提供无 state_key 的字段；有 state_key 的字段由框架自动提取。"
            ),
            required=True,
        )
    ]

    async def execute(
        self, tool_call: ToolCall, context: dict[str, Any] | None = None
    ) -> AgentToolResult:
        ctx = context or {}

        flow_ctx: dict[str, Any] = ctx.get("_flow_context") or {}
        stage_id: str | None = flow_ctx.get("current_stage")
        if not stage_id or stage_id == "__completed__":
            return AgentToolResult.error_result(
                tool_call.id,
                "当前没有待提交的流程阶段（_flow_context.current_stage 未设置或已完成）。",
            )

        skill_name = flow_ctx.get("skill_name", "")

        evaluator = FlowEvaluatorRegistry.get(skill_name)
        if not evaluator:
            return AgentToolResult.error_result(
                tool_call.id,
                f"未找到 skill '{skill_name}' 对应的 evaluator，请确认流程已正确初始化。",
            )

        stage = next((s for s in evaluator.stages if s.id == stage_id), None)
        if not stage:
            return AgentToolResult.error_result(
                tool_call.id,
                f"阶段 '{stage_id}' 不存在于 '{skill_name}' 流程中。",
            )

        user_fields_provided: dict[str, Any] = tool_call.arguments.get("fields") or {}

        # 验证用户提供的字段是否属于当前阶段的用户字段（无 state_key）
        if stage.fields:
            invalid_fields = []
            for field_name in user_fields_provided:
                if field_name not in stage.fields:
                    invalid_fields.append(field_name)
            if invalid_fields:
                return AgentToolResult.error_result(
                    tool_call.id,
                    f"以下字段不属于当前阶段：{invalid_fields}，请确认后重新提交。",
                )

        # 将用户输入写入暂存区 _user_input_{stage_id}
        staging_key = f"_user_input_{stage_id}"
        existing_inputs: dict[str, Any] = dict(flow_ctx.get(staging_key) or {})
        existing_inputs.update(user_fields_provided)

        state_delta: dict[str, Any] = {f"_flow_context.{staging_key}": existing_inputs}

        logger.debug(
            "CollectUserFields: stage=%s fields=%s staging_key=%s",
            stage_id, list(user_fields_provided), staging_key,
        )

        return AgentToolResult.json_result(
            tool_call.id,
            {
                "staged": True,
                "stage_id": stage_id,
                "stage_name": stage.name,
                "message": (
                    f"阶段「{stage.name}」用户数据已暂存。"
                    f"框架将在下一轮自动评估阶段进展。"
                ),
            },
            metadata={"state_delta": state_delta},
        )
