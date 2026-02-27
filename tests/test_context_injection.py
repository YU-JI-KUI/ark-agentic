"""Context injection tests.

测试扁平 context 参数注入功能。
context 结构: {"user_id": "U001", "token_id": "xxx", "account_type": "normal"}
"""

import pytest
import os
from ark_agentic.core.types import ToolCall
from ark_agentic.agents.securities.tools.account_overview import AccountOverviewTool
from ark_agentic.agents.securities.tools.display_card import DisplayCardTool
from ark_agentic.agents.securities.tools.field_extraction import extract_account_overview

# Ensure mock environment
os.environ["SECURITIES_SERVICE_MOCK"] = "true"


@pytest.mark.asyncio
async def test_account_overview_context_injection():
    """测试扁平 context 参数注入和字段提取"""
    tool = AccountOverviewTool()
    
    # 1. Test Normal Account (扁平 context)
    tool_call = ToolCall(id="test_normal", name="account_overview", arguments={})
    context = {
        "user_id": "U001",
        "token_id": "test_token_001",
        "account_type": "normal",
    }
    
    result = await tool.execute(tool_call, context=context)
    data = result.content
    
    # 验证返回的是真实 API 格式
    # Mock 数据现在返回真实 API 格式：{"status": 1, "results": {"rmb": {...}}}
    assert "results" in data or "total_assets" in data
    
    # 使用字段提取工具提取显示字段
    extracted = extract_account_overview(data)
    
    # 普通账户不应该有两融特有字段
    assert extracted.get("net_assets") is None
    assert extracted.get("maintenance_margin_ratio") is None
    
    # 2. Test Margin Account (扁平 context)
    tool_call = ToolCall(id="test_margin", name="account_overview", arguments={})
    context_margin = {
        "user_id": "U001",
        "token_id": "test_token_002",
        "account_type": "margin",
    }
    
    result_margin = await tool.execute(tool_call, context=context_margin)
    data_margin = result_margin.content
    
    # 验证返回的是真实 API 格式
    assert "results" in data_margin or "total_assets" in data_margin
    
    # 使用字段提取工具提取显示字段
    extracted_margin = extract_account_overview(data_margin)
    
    # 两融账户应该有特有字段
    assert extracted_margin.get("net_assets") is not None
    assert extracted_margin.get("total_liabilities") is not None
    assert extracted_margin.get("maintenance_margin_ratio") is not None
    
    print(f"Net Assets: {extracted_margin.get('net_assets')}")
    print(f"Total Liabilities: {extracted_margin.get('total_liabilities')}")
    print(f"Maintenance Margin Ratio: {extracted_margin.get('maintenance_margin_ratio')}")


@pytest.mark.asyncio
async def test_account_overview_with_display_card():
    """测试完整的数据获取 -> 字段提取 -> 卡片渲染流程"""
    # 1. 获取数据 (扁平 context)
    data_tool = AccountOverviewTool()
    data_call = ToolCall(id="test_margin_data", name="account_overview", arguments={})
    context = {
        "user_id": "U001",
        "token_id": "test_token_003",
        "account_type": "margin",
    }
    
    data_result = await data_tool.execute(data_call, context=context)
    
    # 2. 渲染卡片
    card_tool = DisplayCardTool()
    card_call = ToolCall(id="test_margin_card", name="display_card", arguments={"source_tool": "account_overview"})
    
    card_context = {
        "_tool_results_by_name": {
            "account_overview": data_result.content
        }
    }
    
    card_result = await card_tool.execute(card_call, context=card_context)
    
    # 验证卡片模板
    template = card_result.metadata["template"]
    assert template["template_type"] == "account_overview_card"
    
    # 验证两融账户特有字段已渲染
    card_data = template["data"]
    assert card_data.get("net_assets") is not None
    assert card_data.get("total_liabilities") is not None
    assert card_data.get("maintenance_margin_ratio") is not None


if __name__ == "__main__":
    # Manually run if executed as script
    import asyncio
    try:
        asyncio.run(test_account_overview_context_injection())
        print("Context Injection Test PASSED")
    except Exception as e:
        print(f"Test Failed: {e}")
        raise e
