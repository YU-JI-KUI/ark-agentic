"""API 适配器"""

from .account_overview import AccountOverviewAdapter
from .cash_assets import CashAssetsAdapter
from .branch_info import BranchInfoAdapter
from .etf_holdings import ETFHoldingsAdapter
from .fund_holdings import FundHoldingsAdapter
from .hksc_holdings import HKSCHoldingsAdapter
from .security_detail import SecurityDetailAdapter

ADAPTER_REGISTRY = {
    "account_overview": AccountOverviewAdapter,
    "etf_holdings": ETFHoldingsAdapter,
    "hksc_holdings": HKSCHoldingsAdapter,
    "fund_holdings": FundHoldingsAdapter,
    "cash_assets": CashAssetsAdapter,
    "security_detail": SecurityDetailAdapter,
    "branch_info": BranchInfoAdapter,
}

__all__ = [
    "AccountOverviewAdapter",
    "ETFHoldingsAdapter",
    "HKSCHoldingsAdapter",
    "FundHoldingsAdapter",
    "CashAssetsAdapter",
    "SecurityDetailAdapter",
    "BranchInfoAdapter",
    "ADAPTER_REGISTRY",
]
