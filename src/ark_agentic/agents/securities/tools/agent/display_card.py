"""卡片展示工具

显式触发前端数据卡片渲染。从当前轮次的数据工具结果中读取数据，
调用 TemplateRenderer 生成卡片模板并通过 metadata.template 传递给 SSE 管道。

数据工具的 service 层已完成字段提取，此处直接使用已标准化的数据渲染卡片。
"""

from __future__ import annotations

import json
from typing import Any, Literal

from ark_agentic.core.tools.base import AgentTool, ToolParameter
from ark_agentic.core.types import AgentToolResult, ToolCall, ToolResultType
from ark_agentic.core.a2ui.lean_registry import build_lean_payload, register_lean_card

from ...template_renderer import TemplateRenderer


def _get_context_value(
    context: dict[str, Any] | None, key: str, default: Any = None
) -> Any:
    """从 context 获取值，优先 user: 前缀，兼容裸 key"""
    if context is None:
        return default
    prefixed = f"user:{key}"
    if prefixed in context:
        return context[prefixed]
    if key in context:
        return context[key]
    return default


def _mask_account(account: str | None) -> str:
    """脱敏账号：保留前3位和后4位，中间替换为 ****"""
    if not account:
        return "****"
    if len(account) <= 7:
        return account[:3] + "****"
    return account[:3] + "****" + account[-4:]


# 数据工具名 → TemplateRenderer 调用方式
_RENDER_MAP: dict[str, str] = {
    "etf_holdings":             "holdings_list",
    "hksc_holdings":            "holdings_list",
    "fund_holdings":            "holdings_list",
    "account_overview":         "account_overview",
    "cash_assets":              "cash_assets",
    "security_detail":          "security_detail",
    "branch_info":              "branch_info",
    "asset_profit_hist_period":    "asset_profit_hist",
    "asset_profit_hist_range":     "asset_profit_hist",
    "stock_profit_ranking":        "stock_profit_ranking",
    "stock_daily_profit_range":    "stock_daily_profit_calendar",
    "stock_daily_profit_month":    "stock_daily_profit_calendar",
}

_ASSET_CLASS_MAP: dict[str, Literal["ETF", "HKSC", "Fund", "Cash"]] = {
    "etf_holdings": "ETF",
    "hksc_holdings": "HKSC",
    "fund_holdings": "Fund",
}

# Register lean card builders for each preset template type
register_lean_card("account_overview_card", lambda d: d)
register_lean_card("holdings_list_card", lambda d: d)
register_lean_card("cash_assets_card", lambda d: d)
register_lean_card("security_detail_card", lambda d: d)
register_lean_card("branch_info_card", lambda d: d)
register_lean_card("profit_summary_card", lambda d: d)


class DisplayCardTool(AgentTool):
    """在前端展示数据卡片

    将指定数据工具的返回结果渲染为可视化卡片，推送至前端界面。
    必须在调用数据工具之后使用。
    """

    name = "display_card"
    description = (
        "在前端展示数据卡片。在调用数据查询工具（如 etf_holdings、account_overview 等）"
        "获取数据后，必须调用此工具将数据渲染为可视化卡片推送给用户。"
        "参数 source_tool 为之前调用的数据工具名称。"
    )
    thinking_hint = "正在渲染展示卡片…"
    parameters = [
        ToolParameter(
            name="source_tool",
            type="string",
            description=(
                "数据来源工具名，即之前调用的数据工具名称。"
                "可选值：etf_holdings, hksc_holdings, fund_holdings, "
                "account_overview, cash_assets, security_detail, branch_info, "
                "asset_profit_hist_period, asset_profit_hist_range, stock_profit_ranking, "
                "stock_daily_profit_range, stock_daily_profit_month"
            ),
            required=True,
        ),
    ]

    async def execute(
        self,
        tool_call: ToolCall,
        context: dict[str, Any] | None = None,
    ) -> AgentToolResult:
        args = tool_call.arguments
        source_tool = args.get("source_tool", "")

        if source_tool not in _RENDER_MAP:
            return AgentToolResult.error_result(
                tool_call_id=tool_call.id,
                error=f"未知的数据工具: {source_tool}。"
                f"可选值: {', '.join(_RENDER_MAP.keys())}",
            )

        # 从 context 获取数据工具的返回内容（由 runner 注入，或者测试脚本注入）
        tool_results: dict[str, Any] = (context or {}).get("_tool_results_by_name") or (
            context or {}
        )
        source_data: dict[str, Any] = tool_results.get(source_tool) or {}

        if len(source_data) == 0:
            return AgentToolResult.error_result(
                tool_call_id=tool_call.id,
                error=f"未找到 {source_tool} 的数据结果，请先调用 {source_tool} 获取数据。",
            )

        # 解析数据
        data = source_data
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError:
                return AgentToolResult.error_result(
                    tool_call_id=tool_call.id,
                    error=f"{source_tool} 的返回数据格式异常。",
                )

        # 根据工具类型渲染对应卡片
        render_type = _RENDER_MAP[source_tool]
        template: dict[str, Any]

        account = _get_context_value(context, "account")
        masked = _mask_account(account)
        account_type = _get_context_value(context, "account_type", "normal")

        if render_type == "holdings_list":
            asset_class = _ASSET_CLASS_MAP[source_tool]
            _HOLDINGS_TITLE: dict[str, str] = {
                "etf_holdings": f"资金账号：{masked}的ETF资产信息",
                "hksc_holdings": f"资金账号：{masked}的港股通资产信息",
                "fund_holdings": f"资金账号：{masked}的基金资产信息",
            }
            data["title"] = _HOLDINGS_TITLE.get(source_tool, "")
            data["account_type"] = account_type
            template = TemplateRenderer.render_holdings_list_card(asset_class, data)
        elif render_type == "account_overview":
            data["title"] = f"资金账号：{masked}的资产信息"
            data["account_type"] = account_type
            template = TemplateRenderer.render_account_overview_card(data)
        elif render_type == "cash_assets":
            data["title"] = f"资金账号：{masked}的现金资产信息"
            data["account_type"] = account_type
            template = TemplateRenderer.render_cash_assets_card(data)
        elif render_type == "security_detail":
            data["account_type"] = account_type
            template = TemplateRenderer.render_security_detail_card(data)
        elif render_type == "branch_info":
            data["title"] = f"资金账号：{masked}的开户营业部信息"
            data["account_type"] = account_type
            template = TemplateRenderer.render_branch_info_card(data)
        elif render_type == "asset_profit_hist":
            data["title"] = f"资金账号：{masked}的资产历史收益曲线"
            data["account_type"] = account_type
            template = TemplateRenderer.render_asset_profit_hist_card(data)
        elif render_type == "stock_profit_ranking":
            data["title"] = f"资金账号：{masked}的股票盈亏排行"
            template = TemplateRenderer.render_stock_profit_ranking_card(data)
        elif render_type == "stock_daily_profit_calendar":
            data["title"] = f"资金账号：{masked}的股票每日收益"
            data["account_type"] = account_type
            template = TemplateRenderer.render_stock_daily_profit_calendar_card(data)
        else:
            return AgentToolResult.error_result(
                tool_call_id=tool_call.id,
                error=f"不支持的渲染类型: {render_type}",
            )

        return AgentToolResult.a2ui_result(tool_call_id=tool_call.id, data=template)
