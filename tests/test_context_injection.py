"""Context injection tests.

测试扁平 context 参数注入功能。
context 结构: {"user_id": "U001", "token_id": "xxx", "account_type": "normal"}
"""

import pytest
import os
from ark_agentic.core.types import ToolCall
from ark_agentic.agents.securities.tools.account_overview import AccountOverviewTool
from ark_agentic.agents.securities.tools.field_extraction import extract_account_overview

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
    
    # 普通账户不应带出 rzrq 块（空则不出现在 extract 结果中）
    assert "rzrq_assets_info" not in extracted
    
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
    
    rzrq = extracted_margin.get("rzrq_assets_info")
    assert isinstance(rzrq, dict)
    assert rzrq.get("netWorth")
    assert rzrq.get("totalLiabilities")
    assert rzrq.get("mainRatio")

    print(f"rzrq netWorth: {rzrq.get('netWorth')}")
    print(f"rzrq totalLiabilities: {rzrq.get('totalLiabilities')}")
    print(f"rzrq mainRatio: {rzrq.get('mainRatio')}")




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

    rzrq = extracted.get("rzrq_assets_info")
    assert isinstance(rzrq, dict), "若未正确读取 user:account_type 会退化为普通账户，rzrq 缺失"
    assert rzrq.get("netWorth")
    assert rzrq.get("totalLiabilities")


if __name__ == "__main__":
    # Manually run if executed as script
    import asyncio
    try:
        asyncio.run(test_account_overview_context_injection())
        print("Context Injection Test PASSED")
    except Exception as e:
        print(f"Test Failed: {e}")
        raise e
