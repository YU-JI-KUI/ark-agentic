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
        """渲染账户总览卡片
        
        支持的字段（来自真实 API 响应提取）：
        - total_assets: 总资产
        - cash_balance: 现金余额
        - stock_market_value: 股票市值
        - fund_market_value: 基金市值
        - today_profit: 今日收益
        - today_return_rate: 今日收益率
        - account_type: 账户类型 (normal/margin)
        
        两融账户额外字段：
        - net_assets: 净资产
        - total_liabilities: 总负债
        - maintenance_margin_ratio: 维持担保比例
        """
        return {
            "template_type": "account_overview_card",
            "data": {
                # 基础字段
                "total_assets": data.get("total_assets"),
                "cash_balance": data.get("cash_balance"),
                "stock_market_value": data.get("stock_market_value"),
                "fund_market_value": data.get("fund_market_value"),
                "today_profit": data.get("today_profit"),
                "today_return_rate": data.get("today_return_rate"),
                "account_type": "normal" if data.get("account_type", "1") == "1" else "margin",
                # 两融账户额外字段
                "net_assets": data.get("net_assets"),
                "total_liabilities": data.get("total_liabilities"),
                "maintenance_margin_ratio": data.get("maintenance_margin_ratio"),
                # 兼容旧字段（可选）
                "total_profit": data.get("total_profit"),
                "profit_rate": data.get("profit_rate"),
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
        """渲染持仓列表卡片
        
        支持两种数据格式：
        1. 真实 API 格式（通过字段提取）: stock_list, total_market_value, total_profit
        2. 旧格式: holdings, summary
        
        HKSC 额外支持：
        - available_hksc_share: 港股通可用额度
        - pre_frozen_asset: 预冻结资产
        - pre_frozen_list: 预冻结列表
        """
        # 检测数据格式
        if "stock_list" in data:
            # 真实 API 格式
            summary = {
                "total_market_value": data.get("total_market_value") or data.get("hold_market_value"),
                "total_profit": data.get("total_profit") or data.get("day_total_profit"),
                "total_profit_rate": data.get("total_profit_rate") or data.get("day_total_profit_rate"),
                "total": data.get("total"),
            }
            
            # HKSC 特有字段
            if asset_class == "HKSC":
                summary["available_hksc_share"] = data.get("available_hksc_share")
                summary["limit_hksc_share"] = data.get("limit_hksc_share")
                summary["total_hksc_share"] = data.get("total_hksc_share")
                summary["pre_frozen_asset"] = data.get("pre_frozen_asset")
            
            result = {
                "template_type": "holdings_list_card",
                "asset_class": asset_class,
                "data": {
                    "holdings": data.get("stock_list", []),
                    "summary": summary,
                }
            }
            
            # HKSC 预冻结列表
            if asset_class == "HKSC" and data.get("pre_frozen_list"):
                result["data"]["pre_frozen_list"] = data.get("pre_frozen_list")
            
            return result
        else:
            # 旧格式
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
        """渲染现金资产卡片
        
        支持的字段（来自真实 API 响应提取）：
        - cash_balance: 现金总额
        - cash_available: 可用资金
        - draw_balance: 可取资金
        - today_profit: 今日收益
        - accu_profit: 累计收益
        - fund_name: 理财产品名称
        - frozen_funds_total: 冻结资金总额
        - frozen_funds_detail: 冻结资金明细列表
        """
        return {
            "template_type": "cash_assets_card",
            "data": {
                # 基础字段
                "cash_balance": data.get("cash_balance"),
                "cash_available": data.get("cash_available"),
                "draw_balance": data.get("draw_balance"),
                "today_profit": data.get("today_profit"),
                # 扩展字段
                "accu_profit": data.get("accu_profit"),
                "fund_name": data.get("fund_name"),
                "fund_code": data.get("fund_code"),
                "frozen_funds_total": data.get("frozen_funds_total"),
                "frozen_funds_detail": data.get("frozen_funds_detail"),
                "in_transit_asset_total": data.get("in_transit_asset_total"),
                # 兼容旧字段
                "available_cash": data.get("available_cash") or data.get("cash_available"),
                "frozen_cash": data.get("frozen_cash") or data.get("frozen_funds_total"),
                "total_cash": data.get("total_cash") or data.get("cash_balance"),
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

