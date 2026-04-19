"""CommitFlowStageTool — 提交流程阶段完成数据。

LLM 在完成当前阶段的所有业务工具调用后，调用此工具提交阶段数据：
  - source="tool" 的字段：框架自动从 session.state 按 field_sources 声明提取
  - source="user" 的字段：LLM 通过 user_data 参数显式提供

校验通过后写入 _flow_context.stage_<id>，供下次 evaluator 调用时判定阶段推进。
"""

from __future__ import annotations

import logging
from typing import Any

from ..tools.base import AgentTool, ToolParameter, read_string_param_required
from ..types import AgentToolResult, ToolCall
from .base_evaluator import FieldSource, FlowEvaluatorRegistry

logger = logging.getLogger(__name__)


def _extract_field(state_value: Any, fs: FieldSource) -> Any:
    """按 FieldSource 声明从工具结果中提取字段值。"""
    if fs.transform is not None:
        return fs.transform(state_value)
    if fs.path:
        value = state_value
        for part in fs.path.split("."):
            value = value.get(part) if isinstance(value, dict) else None
        return value
    return state_value


class CommitFlowStageTool(AgentTool):
    """提交流程阶段完成数据。

    框架自动提取 source="tool" 字段，LLM 仅需提供 source="user" 字段。
    校验通过后写入 _flow_context.stage_<id>，触发 evaluator 下次调用时推进阶段。
    """

    name = "commit_flow_stage"
    description = (
        "提交当前流程阶段的完成数据。"
        "框架自动从工具结果中提取 tool 来源字段；"
        "LLM 仅需通过 user_data 提供用户对话中收集的字段。"
        "提交成功后请再次调用对应的 flow evaluator 确认阶段推进。"
    )
    group = "flow"

    parameters = [
        ToolParameter(
            name="stage_id",
            type="string",
            description="要提交的阶段 ID（如 identity_verify、options_query、plan_confirm、execute）",
            required=True,
        ),
        ToolParameter(
            name="user_data",
            type="object",
            description=(
                "用户来源字段的键值对（source=user 的字段必须在此提供）。"
                "tool 来源字段无需填写，框架自动从 session.state 提取。"
            ),
            required=False,
        ),
    ]

    async def execute(
        self, tool_call: ToolCall, context: dict[str, Any] | None = None
    ) -> AgentToolResult:
        ctx = context or {}
        args = tool_call.arguments
        stage_id = read_string_param_required(args, "stage_id")
        user_data: dict[str, Any] = args.get("user_data") or {}

        # 从 _flow_context 获取当前 skill_name
        flow_ctx: dict[str, Any] = ctx.get("_flow_context") or {}
        skill_name = flow_ctx.get("skill_name", "")
        if not skill_name:
            return AgentToolResult.error_result(
                tool_call.id,
                "未检测到活跃流程，请先调用 flow evaluator 初始化流程。",
            )

        # 查找 evaluator
        evaluator = FlowEvaluatorRegistry.get(skill_name)
        if not evaluator:
            return AgentToolResult.error_result(
                tool_call.id,
                f"未找到 skill '{skill_name}' 对应的 evaluator。",
            )

        # 查找阶段定义
        stage = next((s for s in evaluator.stages if s.id == stage_id), None)
        if not stage:
            available = [s.id for s in evaluator.stages]
            return AgentToolResult.error_result(
                tool_call.id,
                f"阶段 '{stage_id}' 不存在于 '{skill_name}' 流程。可用阶段：{available}",
            )

        # 收集字段数据
        collected: dict[str, Any] = {}
        missing_state_keys: list[str] = []

        if stage.field_sources:
            for field_name, fs in stage.field_sources.items():
                if fs.source == "tool":
                    if not fs.state_key:
                        logger.warning(
                            "FieldSource for '%s.%s' has source='tool' but no state_key",
                            stage_id, field_name,
                        )
                        continue
                    state_value = ctx.get(fs.state_key)
                    if state_value is None:
                        missing_state_keys.append(fs.state_key)
                        continue
                    collected[field_name] = _extract_field(state_value, fs)
                else:  # source="user"
                    if field_name not in user_data:
                        return AgentToolResult.error_result(
                            tool_call.id,
                            f"用户来源字段 '{field_name}' 未在 user_data 中提供，"
                            f"请从对话上下文中提取该值后重新提交。",
                        )
                    collected[field_name] = user_data[field_name]

            if missing_state_keys:
                return AgentToolResult.error_result(
                    tool_call.id,
                    f"以下工具结果尚未写入 session state：{missing_state_keys}。"
                    f"请先调用相应工具后再提交阶段数据。",
                )
        else:
            # 未声明 field_sources：直接使用 user_data（兼容无 field_sources 的旧阶段）
            collected = dict(user_data)

        # Pydantic 校验
        if stage.output_schema:
            valid, errors = stage.validate_output(collected)
            if not valid:
                return AgentToolResult.error_result(
                    tool_call.id,
                    f"阶段 '{stage.name}' 数据校验失败：{'; '.join(errors)}",
                )

        # 写入 _flow_context.stage_<id>（点路径，不覆盖同级其他 key）
        state_delta = {f"_flow_context.stage_{stage_id}": collected}

        logger.debug("CommitFlowStage: stage=%s data=%s", stage_id, collected)

        return AgentToolResult.json_result(
            tool_call.id,
            {
                "committed": True,
                "stage_id": stage_id,
                "stage_name": stage.name,
                "message": (
                    f"阶段「{stage.name}」数据已提交。"
                    f"请再次调用 {evaluator.name} 确认阶段推进。"
                ),
            },
            metadata={"state_delta": state_delta},
        )
