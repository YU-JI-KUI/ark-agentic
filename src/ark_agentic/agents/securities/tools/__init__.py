"""证券工具包"""

from .account_overview import AccountOverviewTool
from .cash_assets import CashAssetsTool
from .etf_holdings import ETFHoldingsTool
from .fund_holdings import FundHoldingsTool
from .hksc_holdings import HKSCHoldingsTool
from .security_detail import SecurityDetailTool

__all__ = [
    "AccountOverviewTool",
    "CashAssetsTool",
    "ETFHoldingsTool",
    "FundHoldingsTool",
    "HKSCHoldingsTool",
    "SecurityDetailTool",
    "create_securities_tools",
]


def create_securities_tools() -> list:
    """创建所有证券工具"""
    return [
        AccountOverviewTool(),
        CashAssetsTool(),
        ETFHoldingsTool(),
        FundHoldingsTool(),
        HKSCHoldingsTool(),
        SecurityDetailTool(),
    ]
