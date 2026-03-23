"""API 适配器"""

from .account_overview import AccountOverviewAdapter
from .asset_profit_hist import AssetProfitHistAdapter
from .branch_info import BranchInfoAdapter
from .cash_assets import CashAssetsAdapter
from .etf_holdings import ETFHoldingsAdapter
from .fund_holdings import FundHoldingsAdapter
from .hksc_holdings import HKSCHoldingsAdapter
from .security_detail import SecurityDetailAdapter
from .stock_daily_profit import StockDailyProfitAdapter
from .stock_profit_ranking import StockProfitRankingAdapter

ADAPTER_REGISTRY = {
    "account_overview":    AccountOverviewAdapter,
    "asset_profit_hist":   AssetProfitHistAdapter,
    "branch_info":         BranchInfoAdapter,
    "cash_assets":         CashAssetsAdapter,
    "etf_holdings":        ETFHoldingsAdapter,
    "fund_holdings":       FundHoldingsAdapter,
    "hksc_holdings":       HKSCHoldingsAdapter,
    "security_detail":     SecurityDetailAdapter,
    "stock_daily_profit":  StockDailyProfitAdapter,
    "stock_profit_ranking": StockProfitRankingAdapter,
}

__all__ = [
    "AccountOverviewAdapter",
    "AssetProfitHistAdapter",
    "BranchInfoAdapter",
    "CashAssetsAdapter",
    "ETFHoldingsAdapter",
    "FundHoldingsAdapter",
    "HKSCHoldingsAdapter",
    "SecurityDetailAdapter",
    "StockDailyProfitAdapter",
    "StockProfitRankingAdapter",
    "ADAPTER_REGISTRY",
]
