import pytest
import os
from ark_agentic.core.types import ToolCall, ToolResultType
from ark_agentic.agents.securities.tools.account_overview import AccountOverviewTool
from ark_agentic.agents.securities.tools.etf_holdings import ETFHoldingsTool
from ark_agentic.agents.securities.tools.hksc_holdings import HKSCHoldingsTool
from ark_agentic.agents.securities.tools.fund_holdings import FundHoldingsTool
from ark_agentic.agents.securities.tools.cash_assets import CashAssetsTool
from ark_agentic.agents.securities.tools.security_detail import SecurityDetailTool

# Ensure mock environment
os.environ["SECURITIES_SERVICE_MOCK"] = "true"

@pytest.mark.asyncio
async def test_account_overview_card():
    tool = AccountOverviewTool()
    tool_call = ToolCall(id="test_1", name="account_overview", arguments={})
    
    result = await tool.execute(tool_call, context={"user_id": "U001"})
    
    # 检查结果类型
    assert result.result_type == ToolResultType.JSON
    
    # 原始数据在 content 中
    assert "total_assets" in result.content
    
    # 模板在 metadata["template"] 中
    template = result.metadata["template"]
    assert template["template_type"] == "account_overview_card"
    assert "data" in template
    assert template["data"]["account_type"] == "normal"

@pytest.mark.asyncio
async def test_etf_holdings_card():
    tool = ETFHoldingsTool()
    tool_call = ToolCall(id="test_2", name="etf_holdings", arguments={})
    
    result = await tool.execute(tool_call, context={"user_id": "U001"})
    
    assert result.result_type == ToolResultType.JSON
    
    template = result.metadata["template"]
    assert template["template_type"] == "holdings_list_card"
    assert template["asset_class"] == "ETF"
    assert "holdings" in template["data"]

@pytest.mark.asyncio
async def test_hksc_holdings_card():
    tool = HKSCHoldingsTool()
    tool_call = ToolCall(id="test_3", name="hksc_holdings", arguments={})
    
    result = await tool.execute(tool_call, context={"user_id": "U001"})
    
    assert result.result_type == ToolResultType.JSON
        
    template = result.metadata["template"]
    assert template["template_type"] == "holdings_list_card"
    assert template["asset_class"] == "HKSC"

@pytest.mark.asyncio
async def test_fund_holdings_card():
    tool = FundHoldingsTool()
    tool_call = ToolCall(id="test_4", name="fund_holdings", arguments={})
    
    result = await tool.execute(tool_call, context={"user_id": "U001"})
    
    assert result.result_type == ToolResultType.JSON
        
    template = result.metadata["template"]
    assert template["template_type"] == "holdings_list_card"
    assert template["asset_class"] == "Fund"

@pytest.mark.asyncio
async def test_cash_assets_card():
    tool = CashAssetsTool()
    tool_call = ToolCall(id="test_5", name="cash_assets", arguments={})
    
    result = await tool.execute(tool_call, context={"user_id": "U001"})
    
    assert result.result_type == ToolResultType.JSON
        
    template = result.metadata["template"]
    assert template["template_type"] == "cash_assets_card"
    assert "total_cash" in template["data"]

@pytest.mark.asyncio
async def test_security_detail_card():
    tool = SecurityDetailTool()
    tool_call = ToolCall(id="test_6", name="security_detail", arguments={"security_code": "510300"})
    
    result = await tool.execute(tool_call, context={"user_id": "U001"})
    
    assert result.result_type == ToolResultType.JSON
        
    template = result.metadata["template"]
    assert template["template_type"] == "security_detail_card"
    assert template["data"]["security_code"] == "510300"
