"""证券工具包"""

from ark_agentic.core.tools import RenderA2UITool

from ..a2ui import SECURITIES_PRESETS
from .agent import (
    AccountOverviewTool,
    AssetProfitHistPeriodTool,
    AssetProfitHistRangeTool,
    BranchInfoTool,
    CashAssetsTool,
    ETFHoldingsTool,
    FundHoldingsTool,
    HKSCHoldingsTool,
    SecurityDetailTool,
    SecurityInfoSearchTool,
    StockDailyProfitMonthTool,
    StockDailyProfitRangeTool,
    StockProfitRankingTool,
)

__all__ = [
    "AccountOverviewTool",
    "AssetProfitHistPeriodTool",
    "AssetProfitHistRangeTool",
    "BranchInfoTool",
    "CashAssetsTool",
    "ETFHoldingsTool",
    "FundHoldingsTool",
    "HKSCHoldingsTool",
    "RenderA2UITool",
    "SecurityDetailTool",
    "SecurityInfoSearchTool",
    "StockDailyProfitMonthTool",
    "StockDailyProfitRangeTool",
    "StockProfitRankingTool",
    "create_securities_tools",
]


def _create_render_a2ui_tool() -> RenderA2UITool:
    return RenderA2UITool(
        preset=SECURITIES_PRESETS,
        group="securities",
    )


def create_securities_tools() -> list:
    """创建所有证券工具"""
    return [
        AccountOverviewTool(),
        AssetProfitHistPeriodTool(),
        AssetProfitHistRangeTool(),
        BranchInfoTool(),
        CashAssetsTool(),
        ETFHoldingsTool(),
        FundHoldingsTool(),
        HKSCHoldingsTool(),
        SecurityDetailTool(),
        SecurityInfoSearchTool(),
        StockDailyProfitMonthTool(),
        StockDailyProfitRangeTool(),
        StockProfitRankingTool(),
        _create_render_a2ui_tool(),
    ]
