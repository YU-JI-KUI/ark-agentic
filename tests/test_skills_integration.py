"""Skills integration tests.

测试数据工具和 display_card 工具的协作：
1. 数据工具返回原始 API 数据
2. display_card 工具提取字段并渲染模板
"""

import pytest
import os
from ark_agentic.core.types import ToolCall, ToolResultType
from ark_agentic.agents.securities.tools.account_overview import AccountOverviewTool
from ark_agentic.agents.securities.tools.etf_holdings import ETFHoldingsTool
from ark_agentic.agents.securities.tools.hksc_holdings import HKSCHoldingsTool
from ark_agentic.agents.securities.tools.fund_holdings import FundHoldingsTool
from ark_agentic.agents.securities.tools.cash_assets import CashAssetsTool
from ark_agentic.agents.securities.tools.security_detail import SecurityDetailTool
from ark_agentic.agents.securities.tools.display_card import DisplayCardTool

# Ensure mock environment
os.environ["SECURITIES_SERVICE_MOCK"] = "true"


@pytest.mark.asyncio
async def test_account_overview_data_and_card():
    """测试 account_overview 数据获取和卡片渲染"""
    # 1. 获取数据
    data_tool = AccountOverviewTool()
    data_call = ToolCall(id="test_1", name="account_overview", arguments={})
    
    data_result = await data_tool.execute(data_call, context={"user_id": "U001"})
    
    # 数据工具返回原始 JSON 数据
    assert data_result.result_type == ToolResultType.JSON
    assert "total_assets" in data_result.content or "results" in data_result.content
    
    # 2. 渲染卡片
    card_tool = DisplayCardTool()
    card_call = ToolCall(id="test_1_card", name="display_card", arguments={"source_tool": "account_overview"})
    
    # 模拟 runner 注入的上下文
    card_context = {
        "_tool_results_by_name": {
            "account_overview": data_result.content
        }
    }
    
    card_result = await card_tool.execute(card_call, context=card_context)
    
    # 卡片工具返回模板
    assert card_result.result_type == ToolResultType.JSON
    template = card_result.metadata["template"]
    assert template["template_type"] == "account_overview_card"
    assert "data" in template


@pytest.mark.asyncio
async def test_etf_holdings_data_and_card():
    """测试 ETF 持仓数据获取和卡片渲染"""
    data_tool = ETFHoldingsTool()
    data_call = ToolCall(id="test_2", name="etf_holdings", arguments={})
    
    data_result = await data_tool.execute(data_call, context={"user_id": "U001"})
    
    assert data_result.result_type == ToolResultType.JSON
    
    # 渲染卡片
    card_tool = DisplayCardTool()
    card_call = ToolCall(id="test_2_card", name="display_card", arguments={"source_tool": "etf_holdings"})
    
    card_context = {
        "_tool_results_by_name": {
            "etf_holdings": data_result.content
        }
    }
    
    card_result = await card_tool.execute(card_call, context=card_context)
    
    assert card_result.result_type == ToolResultType.JSON
    template = card_result.metadata["template"]
    assert template["template_type"] == "holdings_list_card"
    assert template["asset_class"] == "ETF"


@pytest.mark.asyncio
async def test_hksc_holdings_data_and_card():
    """测试港股通持仓数据获取和卡片渲染"""
    data_tool = HKSCHoldingsTool()
    data_call = ToolCall(id="test_3", name="hksc_holdings", arguments={})
    
    data_result = await data_tool.execute(data_call, context={"user_id": "U001"})
    
    assert data_result.result_type == ToolResultType.JSON
    
    # 渲染卡片
    card_tool = DisplayCardTool()
    card_call = ToolCall(id="test_3_card", name="display_card", arguments={"source_tool": "hksc_holdings"})
    
    card_context = {
        "_tool_results_by_name": {
            "hksc_holdings": data_result.content
        }
    }
    
    card_result = await card_tool.execute(card_call, context=card_context)
    
    assert card_result.result_type == ToolResultType.JSON
    template = card_result.metadata["template"]
    assert template["template_type"] == "holdings_list_card"
    assert template["asset_class"] == "HKSC"


@pytest.mark.asyncio
async def test_fund_holdings_data_and_card():
    """测试基金持仓数据获取和卡片渲染"""
    data_tool = FundHoldingsTool()
    data_call = ToolCall(id="test_4", name="fund_holdings", arguments={})
    
    data_result = await data_tool.execute(data_call, context={"user_id": "U001"})
    
    assert data_result.result_type == ToolResultType.JSON
    
    # 渲染卡片
    card_tool = DisplayCardTool()
    card_call = ToolCall(id="test_4_card", name="display_card", arguments={"source_tool": "fund_holdings"})
    
    card_context = {
        "_tool_results_by_name": {
            "fund_holdings": data_result.content
        }
    }
    
    card_result = await card_tool.execute(card_call, context=card_context)
    
    assert card_result.result_type == ToolResultType.JSON
    template = card_result.metadata["template"]
    assert template["template_type"] == "holdings_list_card"
    assert template["asset_class"] == "Fund"


@pytest.mark.asyncio
async def test_cash_assets_data_and_card():
    """测试现金资产数据获取和卡片渲染"""
    data_tool = CashAssetsTool()
    data_call = ToolCall(id="test_5", name="cash_assets", arguments={})
    
    data_result = await data_tool.execute(data_call, context={"user_id": "U001"})
    
    assert data_result.result_type == ToolResultType.JSON
    
    # 渲染卡片
    card_tool = DisplayCardTool()
    card_call = ToolCall(id="test_5_card", name="display_card", arguments={"source_tool": "cash_assets"})
    
    card_context = {
        "_tool_results_by_name": {
            "cash_assets": data_result.content
        }
    }
    
    card_result = await card_tool.execute(card_call, context=card_context)
    
    assert card_result.result_type == ToolResultType.JSON
    template = card_result.metadata["template"]
    assert template["template_type"] == "cash_assets_card"
    assert "total_cash" in template["data"]


@pytest.mark.asyncio
async def test_security_detail_data_and_card():
    """测试标的详情数据获取和卡片渲染"""
    data_tool = SecurityDetailTool()
    data_call = ToolCall(id="test_6", name="security_detail", arguments={"security_code": "510300"})
    
    data_result = await data_tool.execute(data_call, context={"user_id": "U001"})
    
    assert data_result.result_type == ToolResultType.JSON
    
    # 渲染卡片
    card_tool = DisplayCardTool()
    card_call = ToolCall(id="test_6_card", name="display_card", arguments={"source_tool": "security_detail"})
    
    card_context = {
        "_tool_results_by_name": {
            "security_detail": data_result.content
        }
    }
    
    card_result = await card_tool.execute(card_call, context=card_context)
    
    assert card_result.result_type == ToolResultType.JSON
    template = card_result.metadata["template"]
    assert template["template_type"] == "security_detail_card"
    assert template["data"]["security_code"] == "510300"
