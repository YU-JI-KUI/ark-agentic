"""用户股票每日收益明细工具（按日期区间查询）

底层使用 stock_daily_profit 服务，传入 beginTime + endTime。
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


class StockDailyProfitRangeTool(AgentTool):
    """查询用户指定日期区间的股票每日收益明细"""

    name = "stock_daily_profit_range"
    description = (
        "查询用户指定起止日期区间内的股票每日收益明细，"
        "包括总收益、总收益率及各交易日的收益额和收益率。"
        "begin_time 和 end_time 格式均为 YYYYMMDD（如 20260301）。"
        "支持普通账户和两融账户。"
    )
    thinking_hint = "正在查询股票每日收益明细…"
    parameters = [
        ToolParameter(
            name="begin_time",
            type="integer",
            description="起始日期，格式 YYYYMMDD，例如 20260301",
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

        extra: dict[str, Any] = {}
        for key in ("begin_time", "end_time"):
            val = args.get(key)
            if val is not None:
                extra[key] = val
        context = {**context, **extra}

        try:
            data = await create_service_adapter(
                "stock_daily_profit", context=context
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
