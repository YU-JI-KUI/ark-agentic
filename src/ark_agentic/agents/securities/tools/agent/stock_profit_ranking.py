"""用户股票盈亏排行工具

从 context 获取参数（支持 user: 前缀和裸 key 兼容）：

**validatedata 必需字段**（生产环境必需，Mock 模式可省略）：
- validatedata: 认证字符串

**工具参数（LLM 调用时提供）**：
- pft_type: 排行类型，profit=盈利排行 loss=亏损排行
- period: 时间段枚举，this_week/month_to_date/year_to_date/past_year/since_inception
- limit: 查询条数，默认 10
"""

from __future__ import annotations

from typing import Any

from ark_agentic.core.tools.base import AgentTool, ToolParameter
from ark_agentic.core.types import AgentToolResult, ToolCall

from ..service import create_service_adapter
from .asset_profit_hist_period import PERIOD_TO_TIME_TYPE

PFT_TYPE_MAP: dict[str, int] = {
    "profit": 1,
    "loss":   2,
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


class StockProfitRankingTool(AgentTool):
    """查询用户股票盈亏排行"""

    name = "stock_profit_ranking"
    description = (
        "查询用户股票盈亏排行（仅支持普通账户），包括盈利/亏损股票数量、合计金额及股票列表。"
        "pft_type 指定查盈利还是亏损排行，period 指定时间范围。"
    )
    thinking_hint = "正在查询股票盈亏排行…"
    parameters = [
        ToolParameter(
            name="pft_type",
            type="string",
            description="排行类型：profit=盈利排行 loss=亏损排行",
            required=True,
        ),
        ToolParameter(
            name="period",
            type="string",
            description=(
                "时间段枚举，默认this_week:"
                "this_week=本周 / "
                "month_to_date=月初至今 / "
                "year_to_date=年初至今 / "
                "past_year=过去一年 / "
                "since_inception=开户以来"
            ),
            required=False,
        ),
        ToolParameter(
            name="limit",
            type="integer",
            description="返回条数，默认 10",
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

        pft_type_str = args.get("pft_type", "")
        pft_type = PFT_TYPE_MAP.get(pft_type_str)
        if pft_type is None:
            valid = ", ".join(PFT_TYPE_MAP.keys())
            return AgentToolResult.error_result(
                tool_call_id=tool_call.id,
                error=f"无效的 pft_type 值：{pft_type_str!r}。有效值：{valid}",
            )

        period = args.get("period")
        if period is not None:
            time_type = PERIOD_TO_TIME_TYPE.get(period)
            if time_type is None:
                valid = ", ".join(PERIOD_TO_TIME_TYPE.keys())
                return AgentToolResult.error_result(
                    tool_call_id=tool_call.id,
                    error=f"无效的 period 值：{period!r}。有效值：{valid}",
                )
        else:
            # time_type 不能为空，默认用本周
            time_type = PERIOD_TO_TIME_TYPE["this_week"]

        user_id = _get_context_value(context, "id") or _get_context_value(
            context, "user_id", "U001"
        )

        extra: dict[str, Any] = {"pft_type": pft_type}
        if time_type is not None:
            extra["time_type"] = time_type
        limit = args.get("limit")
        if limit is not None:
            extra["limit"] = limit
        context = {**context, **extra}

        try:
            data = await create_service_adapter(
                "stock_profit_ranking", context=context
            ).call(
                account_type="normal",  # 该接口仅支持普通账户
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
