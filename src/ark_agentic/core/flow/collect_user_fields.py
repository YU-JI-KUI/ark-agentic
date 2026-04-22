"""CollectUserFieldsTool — 向当前流程阶段提交用户提供的字段。

替代原 CommitFlowStageTool，设计差异：
  - 无 stage_id 参数：从 session.state["_flow_stage"] 自动推断
  - 仅需提供 source="user" 的字段；source="tool" 字段由框架自动从 session.state 提取
  - 框架完成校验和持久化写入
"""

from __future__ import annotations

import logging
from typing import Any

from ..tools.base import AgentTool, ToolParameter
from ..types import AgentToolResult, ToolCall
from .base_evaluator import BaseFlowEvaluator, FlowEvaluatorRegistry

logger = logging.getLogger(__name__)


class CollectUserFieldsTool(AgentTool):
    """向当前流程阶段提交用户提供的信息。

    框架自动推断当前阶段（无需 stage_id 参数），并自动从 session.state 提取
    source="tool" 的字段。LLM 只需提供用户对话中收集到的 source="user" 字段。
    """

    name = "collect_user_fields"
    description = (
        "向当前流程阶段提交用户提供的信息。"
        "只需提供用户输入的字段（source=user）；"
        "来自工具调用的字段由框架自动从 session.state 提取。"
        "提交成功后框架将自动推进到下一阶段。"
    )
    group = "flow"

    parameters = [
        ToolParameter(
            name="fields",
            type="object",
            description=(
                "当前阶段需要用户提供的字段键值对。"
                "只提供 source=user 的字段；tool 来源字段无需填写。"
            ),
            required=True,
        )
    ]

    async def execute(
        self, tool_call: ToolCall, context: dict[str, Any] | None = None
    ) -> AgentToolResult:
        ctx = context or {}

        # 从 session.state 推断当前阶段
        stage_id: str | None = ctx.get("_flow_stage")
        if not stage_id or stage_id == "__completed__":
            return AgentToolResult.error_result(
                tool_call.id,
                "当前没有待提交的流程阶段（_flow_stage 未设置或已完成）。",
            )

        flow_ctx: dict[str, Any] = ctx.get("_flow_context") or {}
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

        # 收集所有字段：user 字段来自参数，tool 字段自动提取
        collected: dict[str, Any] = {}
        missing_user_fields: list[str] = []
        missing_tool_keys: list[str] = []

        if stage.field_sources:
            for field_name, fs in stage.field_sources.items():
                if fs.source == "user":
                    if field_name in user_fields_provided:
                        collected[field_name] = user_fields_provided[field_name]
                    else:
                        missing_user_fields.append(field_name)
                else:  # source="tool"
                    if not fs.state_key:
                        logger.warning(
                            "FieldSource for '%s.%s' has source='tool' but no state_key",
                            stage_id, field_name,
                        )
                        continue
                    state_value = ctx.get(fs.state_key)
                    if state_value is None:
                        missing_tool_keys.append(fs.state_key)
                    else:
                        collected[field_name] = BaseFlowEvaluator._extract_field(state_value, fs)
        else:
            # 未声明 field_sources：直接使用提供的 fields
            collected = dict(user_fields_provided)

        if missing_user_fields:
            return AgentToolResult.error_result(
                tool_call.id,
                f"以下用户字段未提供：{missing_user_fields}，请确认后重新提交。",
            )

        if missing_tool_keys:
            return AgentToolResult.error_result(
                tool_call.id,
                f"以下工具结果尚未写入 session state：{missing_tool_keys}，"
                f"请先调用对应工具后再提交。",
            )

        # Pydantic 校验
        if stage.output_schema:
            valid, errors = stage.validate_output(collected)
            if not valid:
                return AgentToolResult.error_result(
                    tool_call.id,
                    f"阶段「{stage.name}」数据校验失败：{'; '.join(errors)}",
                )

        # 构建 state_delta
        state_delta: dict[str, Any] = {f"_flow_context.stage_{stage_id}": collected}

        # checkpoint 阶段：追加到 _flow_context.checkpoints（幂等）
        if stage.checkpoint:
            existing: list[dict[str, Any]] = list(flow_ctx.get("checkpoints") or [])
            existing = [c for c in existing if c.get("stage_id") != stage_id]
            existing.append({
                "stage_id": stage_id,
                "name": stage.name,
                "description": stage.description,
            })
            state_delta["_flow_context.checkpoints"] = existing

        # 快照 source="tool" 字段的原始 state 值（stage_delta），供 resume 时还原
        stage_delta: dict[str, Any] = {}
        if stage.field_sources:
            for fs in stage.field_sources.values():
                if fs.source == "tool" and fs.state_key and fs.state_key not in stage_delta:
                    raw = ctx.get(fs.state_key)
                    if raw is not None:
                        stage_delta[fs.state_key] = raw
        for key in stage.delta_state_keys:
            if key not in stage_delta:
                raw = ctx.get(key)
                if raw is not None:
                    stage_delta[key] = raw
        if stage_delta:
            state_delta[f"_flow_context.stage_{stage_id}_delta"] = stage_delta

        logger.debug(
            "CollectUserFields: stage=%s collected=%s delta_keys=%s",
            stage_id, list(collected), list(stage_delta),
        )

        return AgentToolResult.json_result(
            tool_call.id,
            {
                "committed": True,
                "stage_id": stage_id,
                "stage_name": stage.name,
                "message": (
                    f"阶段「{stage.name}」用户数据已提交。"
                    f"框架将在下一轮自动评估阶段进展。"
                ),
            },
            metadata={"state_delta": state_delta},
        )
