"""智能体工具 (AgentTool)"""

from .account_overview import AccountOverviewTool
from .asset_profit_hist_period import AssetProfitHistPeriodTool
from .asset_profit_hist_range import AssetProfitHistRangeTool
from .branch_info import BranchInfoTool
from .cash_assets import CashAssetsTool
from .display_card import DisplayCardTool
from .etf_holdings import ETFHoldingsTool
from .fund_holdings import FundHoldingsTool
from .hksc_holdings import HKSCHoldingsTool
from .security_detail import SecurityDetailTool
from .security_info_search import SecurityInfoSearchTool
from .stock_daily_profit_month import StockDailyProfitMonthTool
from .stock_daily_profit_range import StockDailyProfitRangeTool
from .stock_profit_ranking import StockProfitRankingTool

__all__ = [
    "AccountOverviewTool",
    "AssetProfitHistPeriodTool",
    "AssetProfitHistRangeTool",
    "BranchInfoTool",
    "CashAssetsTool",
    "DisplayCardTool",
    "ETFHoldingsTool",
    "FundHoldingsTool",
    "HKSCHoldingsTool",
    "SecurityDetailTool",
    "SecurityInfoSearchTool",
    "StockDailyProfitMonthTool",
    "StockDailyProfitRangeTool",
    "StockProfitRankingTool",
    "create_securities_tools",
]


def create_securities_tools() -> list:
    """创建所有证券工具"""
    return [
        AccountOverviewTool(),
        AssetProfitHistPeriodTool(),
        AssetProfitHistRangeTool(),
        BranchInfoTool(),
        CashAssetsTool(),
        DisplayCardTool(),
        ETFHoldingsTool(),
        FundHoldingsTool(),
        HKSCHoldingsTool(),
        SecurityDetailTool(),
        SecurityInfoSearchTool(),
        StockDailyProfitMonthTool(),
        StockDailyProfitRangeTool(),
        StockProfitRankingTool(),
    ]
