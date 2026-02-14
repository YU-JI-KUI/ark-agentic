
import pytest
import os
from ark_agentic.core.types import ToolCall
from ark_agentic.agents.securities.tools.account_overview import AccountOverviewTool

# Ensure mock environment
os.environ["SECURITIES_SERVICE_MOCK"] = "true"

@pytest.mark.asyncio
async def test_account_overview_context_injection():
    tool = AccountOverviewTool()
    
    # 1. Test Normal Account (default/explicit)
    tool_call = ToolCall(id="test_normal", name="account_overview", arguments={})
    context = {"user_id": "U001", "account_type": "normal"}
    
    result = await tool.execute(tool_call, context=context)
    data = result.content
    
    # Should NOT have margin fields or be null
    # In our mock data/adapter, normal account doesn't return margin_ratio in the top level keys usually, 
    # but let's check the data structure.
    # The adapter returns: 
    # { "total_assets": ..., "margin_ratio": None, ... } for normal
    
    assert data.get("margin_ratio") is None
    
    # 2. Test Margin Account (via context)
    tool_call = ToolCall(id="test_margin", name="account_overview", arguments={}) # No args!
    context_margin = {"user_id": "U001", "account_type": "margin"}
    
    result_margin = await tool.execute(tool_call, context=context_margin)
    data_margin = result_margin.content
    
    # Should HAVE margin fields
    # Mock data for margin user has margin_ratio
    assert data_margin.get("margin_ratio") is not None
    print(f"Margin Ratio: {data_margin.get('margin_ratio')}")
    
    # Verify values match mock data (margin_user.json has 2.8)
    # Note: Strings refactor changed this to "2.8" potentially? 
    # Let's check type.
    assert str(data_margin.get("margin_ratio")) == "2.8"

if __name__ == "__main__":
    # Manually run if executed as script
    import asyncio
    try:
        asyncio.run(test_account_overview_context_injection())
        print("Context Injection Test PASSED")
    except Exception as e:
        print(f"Test Failed: {e}")
        # raise e
