"""卡片展示工具

显式触发前端数据卡片渲染。从当前轮次的数据工具结果中读取数据，
调用 TemplateRenderer 生成卡片模板并通过 metadata.template 传递给 SSE 管道。

对于 account_overview，使用字段提取工具从真实 API 格式中提取显示字段。
"""

from __future__ import annotations

import json
from typing import Any

from ark_agentic.core.tools.base import AgentTool, ToolParameter
from ark_agentic.core.types import AgentToolResult, ToolCall

from ..template_renderer import TemplateRenderer
from .field_extraction import extract_account_overview, extract_cash_assets, extract_etf_holdings, extract_hksc_holdings


# 数据工具名 → TemplateRenderer 调用方式
_RENDER_MAP: dict[str, str] = {
    "etf_holdings": "holdings_list",
    "hksc_holdings": "holdings_list",
    "fund_holdings": "holdings_list",
    "account_overview": "account_overview",
    "cash_assets": "cash_assets",
    "security_detail": "security_detail",
}

_ASSET_CLASS_MAP: dict[str, str] = {
    "etf_holdings": "ETF",
    "hksc_holdings": "HKSC",
    "fund_holdings": "Fund",
}


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
    parameters = [
        ToolParameter(
            name="source_tool",
            type="string",
            description=(
                "数据来源工具名，即之前调用的数据工具名称。"
                "可选值：etf_holdings, hksc_holdings, fund_holdings, "
                "account_overview, cash_assets, security_detail"
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

        # 从 context 获取数据工具的返回内容（由 runner 注入，只含原始数据）
        source_data: dict[str, Any] = (
            (context or {}).get(source_tool) or {}
        )

        if source_data is None:
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

        if render_type == "holdings_list":
            asset_class = _ASSET_CLASS_MAP[source_tool]
            
            # ETF 和 HKSC 使用字段提取工具从 API 响应中提取显示字段
            if source_tool == "etf_holdings":
                extracted_data = extract_etf_holdings(data)
                template = TemplateRenderer.render_holdings_list_card(asset_class, extracted_data)
            elif source_tool == "hksc_holdings":
                extracted_data = extract_hksc_holdings(data)
                template = TemplateRenderer.render_holdings_list_card(asset_class, extracted_data)
            else:
                # Fund 暂时使用旧格式
                template = TemplateRenderer.render_holdings_list_card(asset_class, data)
        elif render_type == "account_overview":
            # 使用字段提取工具从 API 响应中提取显示字段
            extracted_data = extract_account_overview(data)
            template = TemplateRenderer.render_account_overview_card(extracted_data)
        elif render_type == "cash_assets":
            # 使用字段提取工具从 API 响应中提取显示字段
            extracted_data = extract_cash_assets(data)
            template = TemplateRenderer.render_cash_assets_card(extracted_data)
        elif render_type == "security_detail":
            template = TemplateRenderer.render_security_detail_card(data)
        else:
            return AgentToolResult.error_result(
                tool_call_id=tool_call.id,
                error=f"不支持的渲染类型: {render_type}",
            )

        return AgentToolResult.json_result(
            tool_call_id=tool_call.id,
            data="卡片已推送至前端展示。",
            metadata={"template": template},
        )
