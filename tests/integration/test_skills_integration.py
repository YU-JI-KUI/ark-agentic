"""Skills integration tests.

数据工具返回原始 API 数据后，由 render_a2ui（preset 模式）从 context 渲染卡片。
"""

import os

import pytest

from ark_agentic.agents.securities.a2ui import SECURITIES_PRESETS
from ark_agentic.agents.securities.tools.agent.account_overview import AccountOverviewTool
from ark_agentic.agents.securities.tools.agent.cash_assets import CashAssetsTool
from ark_agentic.agents.securities.tools.agent.etf_holdings import ETFHoldingsTool
from ark_agentic.agents.securities.tools.agent.fund_holdings import FundHoldingsTool
from ark_agentic.agents.securities.tools.agent.hksc_holdings import HKSCHoldingsTool
from ark_agentic.agents.securities.tools.agent.security_detail import SecurityDetailTool
from ark_agentic.core.tools.render_a2ui import RenderA2UITool
from ark_agentic.core.types import ToolCall, ToolResultType

os.environ["SECURITIES_SERVICE_MOCK"] = "true"


def _render_tool() -> RenderA2UITool:
    return RenderA2UITool(preset=SECURITIES_PRESETS, group="securities")


@pytest.mark.asyncio
async def test_account_overview_data_and_card():
    data_tool = AccountOverviewTool()
    data_call = ToolCall(id="test_1", name="account_overview", arguments={})

    data_result = await data_tool.execute(data_call, context={"user_id": "U001"})

    assert data_result.result_type == ToolResultType.JSON
    assert "total_assets" in data_result.content or "results" in data_result.content

    card_tool = _render_tool()
    card_call = ToolCall(
        id="test_1_card",
        name="render_a2ui",
        arguments={"preset_type": "account_overview"},
    )

    card_context = {"account_overview": data_result.content, "user_id": "U001"}

    card_result = await card_tool.execute(card_call, context=card_context)

    assert card_result.result_type == ToolResultType.A2UI
    template = card_result.content
    assert template["template"] == "queryAccountAssetResultTpl"
    assert "assetData" in template["data"]


@pytest.mark.asyncio
async def test_etf_holdings_data_and_card():
    data_tool = ETFHoldingsTool()
    data_call = ToolCall(id="test_2", name="etf_holdings", arguments={})

    data_result = await data_tool.execute(data_call, context={"user_id": "U001"})

    assert data_result.result_type == ToolResultType.JSON

    card_tool = _render_tool()
    card_call = ToolCall(
        id="test_2_card",
        name="render_a2ui",
        arguments={"preset_type": "etf_holdings"},
    )

    card_context = {"etf_holdings": data_result.content, "user_id": "U001"}

    card_result = await card_tool.execute(card_call, context=card_context)

    assert card_result.result_type == ToolResultType.A2UI
    template = card_result.content
    assert template["template"] == "holdings_list_card"
    assert template["asset_class"] == "ETF"


@pytest.mark.asyncio
async def test_hksc_holdings_data_and_card():
    data_tool = HKSCHoldingsTool()
    data_call = ToolCall(id="test_3", name="hksc_holdings", arguments={})

    data_result = await data_tool.execute(data_call, context={"user_id": "U001"})

    assert data_result.result_type == ToolResultType.JSON

    card_tool = _render_tool()
    card_call = ToolCall(
        id="test_3_card",
        name="render_a2ui",
        arguments={"preset_type": "hksc_holdings"},
    )

    card_context = {"hksc_holdings": data_result.content, "user_id": "U001"}

    card_result = await card_tool.execute(card_call, context=card_context)

    assert card_result.result_type == ToolResultType.A2UI
    template = card_result.content
    assert template["template"] == "holdings_list_card"
    assert template["asset_class"] == "HKSC"


@pytest.mark.asyncio
async def test_fund_holdings_data_and_card():
    data_tool = FundHoldingsTool()
    data_call = ToolCall(id="test_4", name="fund_holdings", arguments={})

    data_result = await data_tool.execute(data_call, context={"user_id": "U001"})

    assert data_result.result_type == ToolResultType.JSON

    card_tool = _render_tool()
    card_call = ToolCall(
        id="test_4_card",
        name="render_a2ui",
        arguments={"preset_type": "fund_holdings"},
    )

    card_context = {"fund_holdings": data_result.content, "user_id": "U001"}

    card_result = await card_tool.execute(card_call, context=card_context)

    assert card_result.result_type == ToolResultType.A2UI
    template = card_result.content
    assert template["template"] == "holdings_list_card"
    assert template["asset_class"] == "Fund"


@pytest.mark.asyncio
async def test_cash_assets_data_and_card():
    data_tool = CashAssetsTool()
    data_call = ToolCall(id="test_5", name="cash_assets", arguments={})

    data_result = await data_tool.execute(data_call, context={"user_id": "U001"})

    assert data_result.result_type == ToolResultType.JSON

    card_tool = _render_tool()
    card_call = ToolCall(
        id="test_5_card",
        name="render_a2ui",
        arguments={"preset_type": "cash_assets"},
    )

    card_context = {"cash_assets": data_result.content, "user_id": "U001"}

    card_result = await card_tool.execute(card_call, context=card_context)

    assert card_result.result_type == ToolResultType.A2UI
    template = card_result.content
    assert template["template"] == "cash_assets_card"
    assert "cash_balance" in template["data"]


@pytest.mark.asyncio
async def test_security_detail_data_and_card():
    data_tool = SecurityDetailTool()
    data_call = ToolCall(
        id="test_6", name="security_detail", arguments={"security_code": "510300"}
    )

    data_result = await data_tool.execute(data_call, context={"user_id": "U001"})

    assert data_result.result_type == ToolResultType.JSON

    card_tool = _render_tool()
    card_call = ToolCall(
        id="test_6_card",
        name="render_a2ui",
        arguments={"preset_type": "security_detail"},
    )

    card_context = {"security_detail": data_result.content, "user_id": "U001"}

    card_result = await card_tool.execute(card_call, context=card_context)

    assert card_result.result_type == ToolResultType.A2UI
    template = card_result.content
    assert template["template"] == "security_detail_card"
    assert template["data"]["security_code"] == "510300"
