"""智能体工具 (AgentTool)"""

from .account_overview import AccountOverviewTool
from .branch_info import BranchInfoTool
from .cash_assets import CashAssetsTool
from .display_card import DisplayCardTool
from .etf_holdings import ETFHoldingsTool
from .fund_holdings import FundHoldingsTool
from .hksc_holdings import HKSCHoldingsTool
from .security_detail import SecurityDetailTool

__all__ = [
    "AccountOverviewTool",
    "BranchInfoTool",
    "CashAssetsTool",
    "DisplayCardTool",
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
        BranchInfoTool(),
        CashAssetsTool(),
        DisplayCardTool(),
        ETFHoldingsTool(),
        FundHoldingsTool(),
        HKSCHoldingsTool(),
        SecurityDetailTool(),
    ]
