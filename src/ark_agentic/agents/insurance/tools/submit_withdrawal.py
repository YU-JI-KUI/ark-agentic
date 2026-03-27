"""SubmitWithdrawalTool — 确认办理取款后提交业务流程

用户明确确认办理后，LLM 调用此工具：
1. 发送 CUSTOM 事件 (start_flow) 到前端
2. 返回 STOP 终止 agent loop
"""

from __future__ import annotations

import logging
from typing import Any

from ark_agentic.core.tools.base import AgentTool, ToolParameter
from ark_agentic.core.types import (
    AgentToolResult,
    CustomToolEvent,
    ToolCall,
    ToolLoopAction,
)

logger = logging.getLogger(__name__)

_SOURCE_TYPE_MAP: dict[str, str] = {
    "shengcunjin": "shengcunjin-claim-E031",
    "bonus": "bonus-claim",
    "loan": "E027Flow",
    "partial": "U045Flow",
    "surrender": "surrender",
}


class SubmitWithdrawalTool(AgentTool):
    name = "submit_withdrawal"
    description = "用户明确确认办理取款操作后调用。提交取款请求并触发业务流程。"
    thinking_hint = "正在提交办理请求…"
    parameters = [
        ToolParameter(
            name="operation_type",
            type="string",
            description="取款类型",
            enum=list(_SOURCE_TYPE_MAP.keys()),
        ),
        ToolParameter(
            name="policies",
            type="array",
            description="保单列表，每项含 policy_no 和 amount",
            items={
                "type": "object",
                "properties": {
                    "policy_no": {"type": "string", "description": "保单号"},
                    "amount": {"type": "string", "description": "金额"},
                },
                "required": ["policy_no", "amount"],
            },
        ),
    ]

    async def execute(
        self, tool_call: ToolCall, context: dict[str, Any] | None = None
    ) -> AgentToolResult:
        args = tool_call.arguments
        operation_type: str = args.get("operation_type", "")
        policies: list[dict[str, str]] = args.get("policies", [])

        source_type = _SOURCE_TYPE_MAP.get(operation_type)
        if source_type is None:
            return AgentToolResult.error_result(
                tool_call.id,
                f"未知的操作类型: {operation_type}，支持: {', '.join(_SOURCE_TYPE_MAP.keys())}",
            )

        query_msg = "，".join(
            f"保单号-{p.get('policy_no', '?')}，金额-{p.get('amount', '?')}"
            for p in policies
        )

        return AgentToolResult.json_result(
            tool_call_id=tool_call.id,
            data={"message": "已提交办理请求"},
            loop_action=ToolLoopAction.STOP,
            events=[
                CustomToolEvent(
                    custom_type="start_flow",
                    payload={"flow_type": source_type, "query_msg": query_msg},
                ),
            ],
        )
