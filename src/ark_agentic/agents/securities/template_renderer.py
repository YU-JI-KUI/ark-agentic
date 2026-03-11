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

        输出格式与业务系统对齐：
        {
          "template": "queryAccountAssetResultTpl",
          "data": {
            "template": "account_overview_card",
            "title": "资金账号：xxx 的资产信息",
            "account_type": "normal" | "margin",
            "assetData": {
              "totalAssetVal": ...,
              "positions": ...,
              "prudentPositions": ...,
              "mktAssetsInfo": { "totalMktVal", "totalMktProfitToday", "totalMktYieldToday" },
              "fundMktAssetsInfo": { "fundMktVal" },
              "cashGainAssetsInfo": { "cashBalance" },
              "rzrqAssetsInfo": { ...原始字段透传... }  # 两融专属，完整保留原始结构
            }
          }
        }
        """
        account_type = data.get("account_type", "normal")

        asset_data: dict[str, Any] = {
            "totalAssetVal": data.get("total_assets", "0.00"),
            "positions": data.get("positions", "--"),
            "prudentPositions": data.get("prudent_positions", ""),
            "mktAssetsInfo": {
                "totalMktVal": data.get("stock_market_value", "0.00"),
                "totalMktProfitToday": data.get("today_profit", "0.00"),
                "totalMktYieldToday": data.get("today_return_rate", "0.00"),
            },
            "fundMktAssetsInfo": {
                "fundMktVal": data.get("fund_market_value", "0.00"),
            },
            "cashGainAssetsInfo": {
                "cashBalance": data.get("cash_balance", "0.00"),
            },
        }

        # 两融账户：直接透传原始 rzrqAssetsInfo 对象，保留所有字段
        rzrq = data.get("rzrq_assets_info")
        if rzrq:
            asset_data["rzrqAssetsInfo"] = rzrq

        return {
            "template": "queryAccountAssetResultTpl",
            "data": {
                "template": "queryAccountAssetResultTpl",
                "title": data.get("title", ""),
                "accountType": account_type,
                "assetData": asset_data,
            },
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
                "totalMarketValue": data.get("total_market_value") or data.get("hold_market_value"),
                "totalProfit": data.get("total_profit") or data.get("day_total_profit"),
                "totalProfitRate": data.get("total_profit_rate") or data.get("day_total_profit_rate"),
                "total": data.get("total"),
            }

            # HKSC 特有字段
            if asset_class == "HKSC":
                summary["availableHkscShare"] = data.get("available_hksc_share")
                summary["limitHkscShare"] = data.get("limit_hksc_share")
                summary["totalHkscShare"] = data.get("total_hksc_share")
                summary["preFrozenAsset"] = data.get("pre_frozen_asset")

            result = {
                "template": "holdings_list_card",
                "assetClass": asset_class,
                "data": {
                    "template": "holdings_list_card",
                    "title": data.get("title", ""),
                    "accountType": data.get("account_type", "normal"),
                    "holdings": data.get("stock_list", []),
                    "summary": summary,
                }
            }

            # HKSC 预冻结列表
            if asset_class == "HKSC" and data.get("pre_frozen_list"):
                result["data"]["preFrozenList"] = data.get("pre_frozen_list")
            
            return result
        else:
            # 旧格式
            return {
                "template": "holdings_list_card",
                "assetClass": asset_class,
                "data": {
                    "template": "holdings_list_card",
                    "title": data.get("title", ""),
                    "accountType": data.get("account_type", "normal"),
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
            "template": "cash_assets_card",
            "data": {
                "template": "cash_assets_card",
                "title": data.get("title", ""),
                "accountType": data.get("account_type", "normal"),
                # 基础字段
                "cashBalance": data.get("cash_balance"),
                "cashAvailable": data.get("cash_available"),
                "drawBalance": data.get("draw_balance"),
                "todayProfit": data.get("today_profit"),
                # 扩展字段
                "accuProfit": data.get("accu_profit"),
                "fundName": data.get("fund_name"),
                "fundCode": data.get("fund_code"),
                "frozenFundsTotal": data.get("frozen_funds_total"),
                "frozenFundsDetail": data.get("frozen_funds_detail"),
                "inTransitAssetTotal": data.get("in_transit_asset_total"),
            }
        }
    
    @staticmethod
    def render_security_detail_card(data: dict[str, Any]) -> dict[str, Any]:
        """渲染具体标的详情卡片"""
        return {
            "template": "security_detail_card",
            "data": {
                "template": "security_detail_card",
                "title": data.get("title", ""),
                "accountType": data.get("account_type", "normal"),
                "securityCode": data.get("security_code"),
                "securityName": data.get("security_name"),
                "securityType": data.get("security_type"),
                "market": data.get("market"),
                "holding": data.get("holding", {}),
                "marketInfo": data.get("market_info", {}),
            }
        }
    
    @staticmethod
    def render_branch_info_card(data: dict[str, Any]) -> dict[str, Any]:
        """渲染开户营业部卡片

        输出格式与账户总览对齐：
        {
          "template": "branch_info_card",
          "data": {
            "template": "branch_info_card",
            "title": "资金账号：xxx 的开户营业部信息",
            "resData": {
              "branchName": ...,
              "address": ...,
              "servicePhone": ...,   # 已清洗，纯号码
              "seatNo": {...}        # 原始字段完整保留
            }
          }
        }
        """
        return {
            "template": "branch_info_card",
            "data": {
                "template": "branch_info_card",
                "title": data.get("title", "开户营业部信息"),
                "accountType": data.get("account_type", "normal"),
                "resData": data.get("branch_info", {}),
            },
        }

    @staticmethod
    def render_profit_summary_card(data: dict[str, Any]) -> dict[str, Any]:
        """渲染收益汇总卡片"""
        return {
            "template": "profit_summary_card",
            "data": {
                "template": "profit_summary_card",
                "title": data.get("title", ""),
                "accountType": data.get("account_type", "normal"),
                "todayProfit": data.get("today_profit"),
                "todayProfitRate": data.get("today_profit_rate"),
                "totalProfit": data.get("total_profit"),
                "totalProfitRate": data.get("total_profit_rate"),
                "topPerformers": data.get("top_performers", []),
            }
        }

