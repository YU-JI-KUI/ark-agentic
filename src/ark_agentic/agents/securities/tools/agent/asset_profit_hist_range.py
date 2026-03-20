"""用户资产历史收益曲线工具（按日期区间查询）

底层使用 asset_profit_hist 服务，固定 timeType=5（自定义区间）。
"""

from __future__ import annotations

from typing import Any

from ark_agentic.core.tools.base import AgentTool, ToolParameter
from ark_agentic.core.types import AgentToolResult, ToolCall

from ..service import create_service_adapter


def _get_context_value(
    context: dict[str, Any] | None, key: str, default: Any = None
) -> Any:
    if context is None:
        return default
    prefixed = f"user:{key}"
    if prefixed in context:
        return context[prefixed]
    if key in context:
        return context[key]
    return default


class AssetProfitHistRangeTool(AgentTool):
    """查询用户指定日期区间的资产历史收益曲线"""

    name = "asset_profit_hist_range"
    description = (
        "查询用户指定起止日期区间的资产历史收益曲线，包括累计总收益、累计收益率及资产序列。"
        "begin_time 和 end_time 格式均为 YYYYMMDD（如 20260101）。"
        "支持普通账户和两融账户。"
    )
    thinking_hint = "正在查询资产历史收益曲线…"
    parameters = [
        ToolParameter(
            name="begin_time",
            type="integer",
            description="起始日期，格式 YYYYMMDD，例如 20260101",
            required=True,
        ),
        ToolParameter(
            name="end_time",
            type="integer",
            description="结束日期，格式 YYYYMMDD，例如 20260319",
            required=True,
        ),
        ToolParameter(
            name="account_type",
            type="string",
            description="账户类型：normal（普通账户）或 margin（两融账户），默认 normal",
            required=False,
        ),
    ]

    async def execute(
        self,
        tool_call: ToolCall,
        context: dict[str, Any] | None = None,
    ) -> AgentToolResult:
        args = tool_call.arguments or {}
        context = context or {}

        account_type = _get_context_value(
            context, "account_type", args.get("account_type", "normal")
        )
        user_id = _get_context_value(context, "id") or _get_context_value(
            context, "user_id", "U001"
        )

        extra: dict[str, Any] = {"time_type": 5}
        for key in ("begin_time", "end_time"):
            val = args.get(key)
            if val is not None:
                extra[key] = val
        context = {**context, **extra}

        try:
            data = await create_service_adapter(
                "asset_profit_hist", context=context
            ).call(
                account_type=account_type,
                user_id=user_id,
                _context=context,
            )
            return AgentToolResult.json_result(
                tool_call_id=tool_call.id,
                data=data,
                metadata={"state_delta": {self.name: data}},
            )
        except Exception as e:
            return AgentToolResult.error_result(
                tool_call_id=tool_call.id,
                error=str(e),
            )
