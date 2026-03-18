"""Context injection tests.

测试扁平 context 参数注入功能。
context 结构: {"user_id": "U001", "token_id": "xxx", "account_type": "normal"}
"""

import pytest
import os
from ark_agentic.core.types import ToolCall
from ark_agentic.agents.securities.tools.agent.account_overview import AccountOverviewTool
from ark_agentic.agents.securities.tools.service.field_extraction import extract_account_overview

# Ensure mock environment
os.environ["SECURITIES_SERVICE_MOCK"] = "true"


@pytest.mark.asyncio
async def test_account_overview_context_injection():
    """测试扁平 context 参数注入和字段提取"""
    os.environ["SECURITIES_SERVICE_MOCK"] = "true"
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
    
    # 两融账户应该有特有字段（整体透传为 rzrq_assets_info 对象）
    rzrq = extracted_margin.get("rzrq_assets_info") or {}
    assert rzrq.get("netWorth") is not None
    assert rzrq.get("totalLiabilities") is not None
    assert rzrq.get("mainRatio") is not None

    print(f"Net Assets: {rzrq.get('netWorth')}")
    print(f"Total Liabilities: {rzrq.get('totalLiabilities')}")
    print(f"Maintenance Margin Ratio: {rzrq.get('mainRatio')}")




@pytest.mark.asyncio
async def test_account_overview_prefixed_context_injection():
    """测试 user: 前缀 context 参数注入（user:id / user:account_type / user:token_id）。"""
    os.environ["SECURITIES_SERVICE_MOCK"] = "true"
    tool = AccountOverviewTool()

    tool_call = ToolCall(id="test_prefixed_margin", name="account_overview", arguments={})
    context = {
        "user:id": "U001",
        "user:token_id": "test_token_prefixed",
        "user:account_type": "margin",
    }

    result = await tool.execute(tool_call, context=context)
    data = result.content

    # 使用字段提取工具提取显示字段
    extracted = extract_account_overview(data)

    # 两融账户应具备特有字段；若未正确读取 user:account_type 会退化为普通账户
    rzrq = extracted.get("rzrq_assets_info") or {}
    assert rzrq.get("netWorth") is not None
    assert rzrq.get("totalLiabilities") is not None
    assert rzrq.get("mainRatio") is not None


if __name__ == "__main__":
    # Manually run if executed as script
    import asyncio
    try:
        asyncio.run(test_account_overview_context_injection())
        print("Context Injection Test PASSED")
    except Exception as e:
        print(f"Test Failed: {e}")
        raise e
