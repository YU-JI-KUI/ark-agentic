"""
模板渲染器

负责将数据渲染为 JSON 模板卡片，用于 AG-UI 企业版协议。
"""

from __future__ import annotations

from typing import Any, Literal


class TemplateRenderer:
    """模板渲染器"""
    
    @staticmethod
    def render_account_overview_card(data: dict[str, Any]) -> dict[str, Any]:
        """渲染账户总览卡片"""
        return {
            "template_type": "account_overview_card",
            "data": {
                "total_assets": data.get("total_assets"),
                "cash_balance": data.get("cash_balance"),
                "stock_market_value": data.get("stock_market_value"),
                "today_profit": data.get("today_profit"),
                "total_profit": data.get("total_profit"),
                "profit_rate": data.get("profit_rate"),
                "account_type": data.get("account_type", "normal"),
                # 两融账户额外字段
                "margin_ratio": data.get("margin_ratio"),
                "risk_level": data.get("risk_level"),
                "update_time": data.get("update_time"),
            }
        }
    
    @staticmethod
    def render_holdings_list_card(
        asset_class: Literal["ETF", "HKSC", "Fund", "Cash"],
        data: dict[str, Any],
    ) -> dict[str, Any]:
        """渲染持仓列表卡片"""
        return {
            "template_type": "holdings_list_card",
            "asset_class": asset_class,
            "data": {
                "holdings": data.get("holdings", []),
                "summary": data.get("summary", {}),
            }
        }
    
    @staticmethod
    def render_cash_assets_card(data: dict[str, Any]) -> dict[str, Any]:
        """渲染现金资产卡片"""
        return {
            "template_type": "cash_assets_card",
            "data": {
                "available_cash": data.get("available_cash"),
                "frozen_cash": data.get("frozen_cash"),
                "total_cash": data.get("total_cash"),
                "update_time": data.get("update_time"),
            }
        }
    
    @staticmethod
    def render_security_detail_card(data: dict[str, Any]) -> dict[str, Any]:
        """渲染具体标的详情卡片"""
        return {
            "template_type": "security_detail_card",
            "data": {
                "security_code": data.get("security_code"),
                "security_name": data.get("security_name"),
                "security_type": data.get("security_type"),
                "market": data.get("market"),
                "holding": data.get("holding", {}),
                "market_info": data.get("market_info", {}),
            }
        }
    
    @staticmethod
    def render_profit_summary_card(data: dict[str, Any]) -> dict[str, Any]:
        """渲染收益汇总卡片"""
        return {
            "template_type": "profit_summary_card",
            "data": {
                "today_profit": data.get("today_profit"),
                "today_profit_rate": data.get("today_profit_rate"),
                "total_profit": data.get("total_profit"),
                "total_profit_rate": data.get("total_profit_rate"),
                "top_performers": data.get("top_performers", []),
            }
        }


def should_return_template(user_input: str, intent: str) -> bool:
    """
    判断是否应该返回 JSON 模板卡片
    
    Args:
        user_input: 用户输入
        intent: 识别的意图（account_overview, etf_holdings 等）
    
    Returns:
        True 表示返回模板，False 表示返回 Markdown 文本
    """
    # 简单的启发式规则：
    # 1. 优先检查分析性关键词
    # 2. 如果包含分析性关键词，返回 Markdown
    # 3. 否则根据输入长度判断
    
    analysis_keywords = [
        "为什么", "怎么样", "分析", "建议", "原因", "对比",
        "合理", "风险", "趋势", "预测", "评价", "如何",
    ]
    
    # 如果包含分析性关键词，返回 Markdown
    for keyword in analysis_keywords:
        if keyword in user_input:
            return False
    
    # 如果输入很短（<= 10 字），返回模板
    if len(user_input) <= 10:
        return True
    
    # 默认：输入较短返回模板，较长返回 Markdown
    return len(user_input) <= 15
