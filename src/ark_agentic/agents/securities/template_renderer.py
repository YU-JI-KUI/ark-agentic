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

