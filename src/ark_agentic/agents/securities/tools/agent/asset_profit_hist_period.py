"""用户资产历史收益曲线工具（按预定义时间段查询）

底层使用 asset_profit_hist 服务，period 枚举字符串映射到 API 的 timeType 整数。
"""

from __future__ import annotations

from typing import Any

from ark_agentic.core.tools.base import AgentTool, ToolParameter
from ark_agentic.core.types import AgentToolResult, ToolCall

from ..service import create_service_adapter

PERIOD_TO_TIME_TYPE: dict[str, int] = {
    "this_week":       15,  # 本周
    "month_to_date":    1,  # 月初至今
    "year_to_date":     3,  # 年初至今
    "past_year":        4,  # 过去一年
    "since_inception": 13,  # 开户以来
}


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


class AssetProfitHistPeriodTool(AgentTool):
    """查询用户按预定义时间段的资产历史收益曲线"""

    name = "asset_profit_hist_period"
    description = (
        "查询用户按预定义时间段的资产历史收益曲线，包括累计总收益、累计收益率及资产序列。"
        "period 可选值：this_week（本周）/ month_to_date（月初至今）/ "
        "year_to_date（年初至今）/ past_year（过去一年）/ since_inception（开户以来）。"
        "支持普通账户和两融账户。"
    )
    thinking_hint = "正在查询资产历史收益曲线…"
    parameters = [
        ToolParameter(
            name="period",
            type="string",
            description=(
                "时间段枚举："
                "this_week=本周 / "
                "month_to_date=月初至今 / "
                "year_to_date=年初至今 / "
                "past_year=过去一年 / "
                "since_inception=开户以来"
            ),
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

        period = args.get("period", "")
        time_type = PERIOD_TO_TIME_TYPE.get(period)
        if time_type is None:
            valid = ", ".join(PERIOD_TO_TIME_TYPE.keys())
            return AgentToolResult.error_result(
                tool_call_id=tool_call.id,
                error=f"无效的 period 值：{period!r}。有效值：{valid}",
            )

        account_type = _get_context_value(
            context, "account_type", args.get("account_type", "normal")
        )
        user_id = _get_context_value(context, "id") or _get_context_value(
            context, "user_id", "U001"
        )

        context = {**context, "time_type": time_type}

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
