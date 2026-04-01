"""用户资产历史收益曲线工具（按预定义时间段查询）

底层使用 asset_profit_hist 服务，period 枚举字符串映射到 API 的 timeType 整数。
"""

from __future__ import annotations

from datetime import date, timedelta
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

_PERIOD_LABEL: dict[str, str] = {
    "this_week":       "本周",
    "month_to_date":   "近一个月",
    "year_to_date":    "年初至今",
    "past_year":       "过去一年",
    "since_inception": "开户以来",
}


def build_period_description(period: str, today: date | None = None) -> str:
    """根据 period 枚举构建可读时间段描述，例如：近一个月：2026年02月19日-至今"""
    if today is None:
        today = date.today()
    label = _PERIOD_LABEL.get(period, period)

    if period == "this_week":
        start = today - timedelta(days=today.weekday())  # 本周一
    elif period == "month_to_date":
        start = today - timedelta(days=30)
    elif period == "year_to_date":
        start = today.replace(month=1, day=1)
    elif period == "past_year":
        try:
            start = today.replace(year=today.year - 1)
        except ValueError:  # 2/29 闰年边界
            start = today.replace(year=today.year - 1, day=28)
    elif period == "since_inception":
        return "开户以来"
    else:
        return label

    return f"{label}：{start.year}年{start.month:02d}月{start.day:02d}日-至今"


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
