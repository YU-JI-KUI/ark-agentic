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
            "template": "queryAccountAssetResultTpl",
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
                "account_type": account_type,
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
            # 通用字段格式
            summary = {
                "total_market_value": data.get("total_market_value") or data.get("hold_market_value"),
                "total_profit": data.get("total_profit") or data.get("day_total_profit"),
                "total_profit_rate": data.get("total_profit_rate") or data.get("day_total_profit_rate"),
            }
            # total 不一定存在
            if "total" in data:
                summary["total"] = data.get("total")

            # HKSC 特有字段
            if asset_class == "HKSC":
                summary["hold_market_value"] = data.get("hold_market_value")
                summary["hold_position_profit"] = data.get("hold_position_profit")
                summary["day_total_profit"] = data.get("day_total_profit")
                summary["day_total_profit_rate"] = data.get("day_total_profit_rate")
                summary["available_hksc_share"] = data.get("available_hksc_share")
                summary["limit_hksc_share"] = data.get("limit_hksc_share")
                summary["total_hksc_share"] = data.get("total_hksc_share")
                summary["pre_frozen_asset"] = data.get("pre_frozen_asset")

            result = {
                "template": "holdings_list_card",
                "asset_class": asset_class,
                "data": {
                    "template": "holdings_list_card",
                    "title": data.get("title", ""),
                    "account_type": data.get("account_type", "normal"),
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
                "template": "holdings_list_card",
                "asset_class": asset_class,
                "data": {
                    "template": "holdings_list_card",
                    "title": data.get("title", ""),
                    "account_type": data.get("account_type", "normal"),
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
        - settlement_date: 结算日期（MM-DD）
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
                "account_type": data.get("account_type", "normal"),
                # 基础字段
                "cash_balance": data.get("cash_balance"),
                "cash_available": data.get("cash_available"),
                "draw_balance": data.get("draw_balance"),
                "settlement_date": data.get("settlement_date"),
                "today_profit": data.get("today_profit"),
                # 扩展字段
                "accu_profit": data.get("accu_profit"),
                "fund_name": data.get("fund_name"),
                "fund_code": data.get("fund_code"),
                "frozen_funds_total": data.get("frozen_funds_total"),
                "frozen_funds_detail": data.get("frozen_funds_detail"),
                "in_transit_asset_total": data.get("in_transit_asset_total"),
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
                "account_type": data.get("account_type", "normal"),
                "security_code": data.get("security_code"),
                "security_name": data.get("security_name"),
                "security_type": data.get("security_type"),
                "market": data.get("market"),
                "holding": data.get("holding", {}),
                "market_info": data.get("market_info", {}),
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
                "account_type": data.get("account_type", "normal"),
                "resData": data.get("branch_info", {}),
            },
        }

    @staticmethod
    def render_asset_profit_hist_card(data: dict[str, Any]) -> dict[str, Any]:
        """渲染资产历史收益曲线卡片

        输出格式：
        {
          "template": "assetProfitHistTpl",
          "data": {
            "template": "assetProfitHistTpl",
            "title": "...",
            "account_type": "normal" | "margin",
            "total_profit": "3182.50",
            "total_profit_rate": "0.0318",
            "asset": ["100000.00", ...],         # 期初→期末资产序列
            "asset_total": ["500000.00", ...]    # 两融专属：期初→期末总资产序列
          }
        }
        """
        result: dict[str, Any] = {
            "template": "assetProfitHistTpl",
            "data": {
                "template": "assetProfitHistTpl",
                "title": data.get("title", ""),
                "account_type": data.get("account_type", "normal"),
                "total_profit": data.get("total_profit"),
                "total_profit_rate": data.get("total_profit_rate"),
                "asset": data.get("asset", []),
            },
        }
        # 两融账户特有字段
        if data.get("asset_total"):
            result["data"]["asset_total"] = data["asset_total"]
        return result

    @staticmethod
    def render_stock_profit_ranking_card(data: dict[str, Any]) -> dict[str, Any]:
        """渲染股票盈亏排行卡片

        输出格式：
        {
          "template": "stockProfitRankingTpl",
          "data": {
            "template": "stockProfitRankingTpl",
            "title": "...",
            "profit_count": "4",
            "profit_amount": "13682.50",
            "loss_count": "6",
            "loss_amount": "-8934.20",
            "stock_list": [
              {"name": "宁德时代", "profit": "4820.30",
               "profit_rate": "0.0921", "profit_ratio": "0.3523"},
              ...
            ]
          }
        }
        """
        return {
            "template": "stockProfitRankingTpl",
            "data": {
                "template": "stockProfitRankingTpl",
                "title": data.get("title", ""),
                "profit_count": data.get("profit_count"),
                "profit_amount": data.get("profit_amount"),
                "loss_count": data.get("loss_count"),
                "loss_amount": data.get("loss_amount"),
                "stock_list": data.get("stock_list", []),
            },
        }

    @staticmethod
    def render_stock_daily_profit_calendar_card(data: dict[str, Any]) -> dict[str, Any]:
        """渲染股票每日收益日历卡片

        输出格式：
        {
          "template": "stockDailyProfitCalendarTpl",
          "data": {
            "template": "stockDailyProfitCalendarTpl",
            "title": "...",
            "account_type": "normal" | "margin",
            "total_profit": "-856.30",
            "total_profit_rate": "-0.0086",
            "trading_dates":     ["20260303", "20260304", ...],
            "daily_profit":      ["-310.20", "448.90", "休市", ...],
            "daily_profit_rate": ["-0.0031", "0.0045", "休市", ...],
          }
        }
        """
        return {
            "template": "stockDailyProfitCalendarTpl",
            "data": {
                "template": "stockDailyProfitCalendarTpl",
                "title": data.get("title", ""),
                "account_type": data.get("account_type", "normal"),
                "total_profit": data.get("total_profit"),
                "total_profit_rate": data.get("total_profit_rate"),
                "trading_dates": data.get("trading_dates", []),
                "daily_profit": data.get("daily_profit", []),
                "daily_profit_rate": data.get("daily_profit_rate", []),
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
                "account_type": data.get("account_type", "normal"),
                "today_profit": data.get("today_profit"),
                "today_profit_rate": data.get("today_profit_rate"),
                "total_profit": data.get("total_profit"),
                "total_profit_rate": data.get("total_profit_rate"),
                "top_performers": data.get("top_performers", []),
            }
        }

    @staticmethod
    def render_dividend_info_card(data: dict[str, Any]) -> dict[str, Any]:
        """渲染分红信息卡片

        输入来自 DividendInfo.model_dump()，字段说明：
        - stat_date:         统计日期
        - market_type:       市场代码（SH/SZ/BJ）
        - stock_code:        6 位股票代码
        - dividend_list:     分红记录列表，每项含 year/assign_type_*/stk_div_type_*/plan 等
        """
        dividend_list = data.get("dividend_list") or []
        # 取第一条记录的 stock_name 作为卡片标题
        first_name = dividend_list[0].get("stock_name") if dividend_list else None
        stock_label = first_name or data.get("stock_code") or "股票"
        return {
            "template": "dividend_info_card",
            "data": {
                "template": "dividend_info_card",
                "title": f"{stock_label} 分红历史",
                "stock_code": data.get("stock_code"),
                "market_type": data.get("market_type"),
                "stat_date": data.get("stat_date"),
                "dividend_list": dividend_list,
            },
        }
