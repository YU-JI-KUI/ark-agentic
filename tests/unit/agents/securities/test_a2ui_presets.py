"""Securities PresetRegistry: registered types and minimal extractor wiring."""

import pytest

from ark_agentic.agents.securities.a2ui import SECURITIES_PRESETS
from ark_agentic.core.types import ToolCall, ToolResultType
from ark_agentic.core.tools.render_a2ui import RenderA2UITool


def test_securities_presets_expected_types():
    types = SECURITIES_PRESETS.types
    assert len(types) == 12
    for name in (
        "etf_holdings",
        "hksc_holdings",
        "fund_holdings",
        "account_overview",
        "cash_assets",
        "security_detail",
        "branch_info",
        "asset_profit_hist_period",
        "asset_profit_hist_range",
        "stock_profit_ranking",
        "stock_daily_profit_range",
        "stock_daily_profit_month",
    ):
        assert name in types


def test_securities_render_a2ui_schema_enum_matches_registry():
    tool = RenderA2UITool(preset=SECURITIES_PRESETS, group="securities")
    props = tool.get_json_schema()["function"]["parameters"]["properties"]
    assert props["preset_type"]["enum"] == SECURITIES_PRESETS.types


@pytest.mark.asyncio
async def test_securities_preset_etf_holdings_happy_path():
    tool = RenderA2UITool(preset=SECURITIES_PRESETS, group="securities")
    etf_data = {
        "stock_list": [{"secuCode": "510300", "secuName": "沪深300ETF", "mktVal": 100}],
        "total_market_value": 100,
        "total_profit": 0,
        "total": 1,
    }
    ctx = {"etf_holdings": etf_data, "user_id": "U1"}
    tc = ToolCall.create("render_a2ui", {"preset_type": "etf_holdings"})
    result = await tool.execute(tc, ctx)
    assert not result.is_error
    assert result.result_type == ToolResultType.A2UI
    assert result.content["template"] == "holdings_list_card"
    assert result.content["asset_class"] == "ETF"
    assert len(result.content["data"]["holdings"]) == 1
