"""用户股票每日收益明细工具（按月份查询）

底层使用 stock_daily_profit 服务，传入 month（YYYYMM）。
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


class StockDailyProfitMonthTool(AgentTool):
    """查询用户指定月份的股票每日收益明细"""

    name = "stock_daily_profit_month"
    description = (
        "查询用户指定月份的股票每日收益明细，"
        "包括总收益、总收益率及各交易日的收益额和收益率。"
        "month 格式为 YYYYMM（如 202603 表示 2026 年 3 月）。"
        "支持普通账户和两融账户。"
    )
    data_source = True
    thinking_hint = "正在查询股票每日收益明细…"
    parameters = [
        ToolParameter(
            name="month",
            type="integer",
            description="查询月份，格式 YYYYMM，例如 202603",
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

        month = args.get("month")
        if month is not None:
            context = {**context, "month": month}

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
