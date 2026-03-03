"""
测试 SSE 模板事件

验证模板数据通过 tool_results.metadata.template 传递到前端的流程。
"""

import asyncio
import json
import os
import sys

# 添加 src 到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


def test_template_renderer():
    """测试 TemplateRenderer 生成正确的模板结构"""
    print("=" * 60)
    print("测试 TemplateRenderer")
    print("=" * 60)

    from ark_agentic.agents.securities.template_renderer import TemplateRenderer

    # 测试 1: account_overview_card
    print("\n1. 测试 account_overview_card...")
    data = {
        "total_assets": "1250000.50",
        "cash_balance": "50000.00",
        "stock_market_value": "1200000.50",
        "today_profit": "15000.00",
        "total_profit": "250000.00",
        "profit_rate": "25.0",
        "account_type": "normal",
        "update_time": "2026-02-16 15:00:00",
    }
    template = TemplateRenderer.render_account_overview_card(data)
    assert template["template_type"] == "account_overview_card"
    assert template["data"]["total_assets"] == "1250000.50"
    print(f"   ✓ template_type={template['template_type']}")

    # 测试 2: holdings_list_card
    print("\n2. 测试 holdings_list_card...")
    data = {
        "holdings": [{"code": "510300", "name": "沪深300ETF"}],
        "summary": {"total_value": "48000"},
    }
    template = TemplateRenderer.render_holdings_list_card("ETF", data)
    assert template["template_type"] == "holdings_list_card"
    assert template["asset_class"] == "ETF"
    assert len(template["data"]["holdings"]) == 1
    print(f"   ✓ template_type={template['template_type']}, asset_class={template['asset_class']}")

    # 测试 3: cash_assets_card
    print("\n3. 测试 cash_assets_card...")
    data = {"available_cash": "50000", "frozen_cash": "0", "total_cash": "50000"}
    template = TemplateRenderer.render_cash_assets_card(data)
    assert template["template_type"] == "cash_assets_card"
    print(f"   ✓ template_type={template['template_type']}")

    # 测试 4: security_detail_card
    print("\n4. 测试 security_detail_card...")
    data = {"security_code": "510300", "security_name": "沪深300ETF"}
    template = TemplateRenderer.render_security_detail_card(data)
    assert template["template_type"] == "security_detail_card"
    print(f"   ✓ template_type={template['template_type']}")

    print("\n" + "=" * 60)
    print("✅ TemplateRenderer 测试通过！")
    print("=" * 60)
    return True


def test_tool_result_carries_template():
    """测试工具结果通过 metadata.template 携带模板数据"""
    print("\n" + "=" * 60)
    print("测试工具结果携带模板数据")
    print("=" * 60)

    from ark_agentic.core.types import AgentToolResult

    # 模拟工具返回（与 etf_holdings.py 等工具的实际行为一致）
    template = {
        "template_type": "holdings_list_card",
        "asset_class": "ETF",
        "data": {"holdings": [], "summary": {}},
    }
    result = AgentToolResult.json_result(
        tool_call_id="test_001",
        data={"holdings": []},
        metadata={"template": template},
    )

    # 验证 metadata 中包含 template
    assert "template" in result.metadata
    assert result.metadata["template"]["template_type"] == "holdings_list_card"
    print("   ✓ metadata.template 存在且 template_type 正确")

    # 验证模板提取逻辑（与 app.py run_agent() 中的逻辑一致）
    extracted = result.metadata.get("template") if result.metadata else None
    assert extracted is not None
    assert isinstance(extracted, dict) and "template_type" in extracted
    print("   ✓ 模板提取逻辑验证通过")

    print("\n" + "=" * 60)
    print("✅ 工具结果模板测试通过！")
    print("=" * 60)
    return True


def test_sse_event_model():
    """测试 SSE 事件模型可以正确携带模板数据"""
    print("\n" + "=" * 60)
    print("测试 SSE 事件模型")
    print("=" * 60)

    from ark_agentic.api.models import SSEEvent

    template = {
        "template_type": "account_overview_card",
        "data": {"total_assets": 1000000.00},
    }
    event = SSEEvent(
        type="response.template",
        seq=1,
        run_id="test-run",
        session_id="test-session",
        template=template,
    )

    # 验证序列化
    serialized = event.model_dump_json(exclude_none=True)
    parsed = json.loads(serialized)
    assert parsed["type"] == "response.template"
    assert parsed["template"]["template_type"] == "account_overview_card"
    print(f"   ✓ SSE event type={parsed['type']}")
    print(f"   ✓ template_type={parsed['template']['template_type']}")

    print("\n" + "=" * 60)
    print("✅ SSE 事件模型测试通过！")
    print("=" * 60)
    return True


def test_display_card_tool():
    """测试 DisplayCardTool 从 context 读取数据工具结果并渲染卡片"""
    print("\n" + "=" * 60)
    print("测试 DisplayCardTool")
    print("=" * 60)

    from ark_agentic.core.types import AgentToolResult, ToolCall, ToolResultType

    # 模拟数据工具结果（etf_holdings 返回的原始数据，符合真实 API 格式）
    etf_data = {
        "results": {
            "dayTotalMktVal": 48000,
            "dayTotalPft": 3000,
            "stockList": [{"secuCode": "510300", "secuName": "沪深300ETF", "mktVal": 48000}],
        }
    }

    # 模拟 runner 注入的 context（state_delta 会将工具结果合并到 state）
    context = {
        "etf_holdings": etf_data,
        "user_id": "U001",
    }

    # 创建 DisplayCardTool 并执行
    from ark_agentic.agents.securities.tools.display_card import DisplayCardTool

    tool = DisplayCardTool()
    tc = ToolCall.create(name="display_card", arguments={"source_tool": "etf_holdings"})

    result = asyncio.get_event_loop().run_until_complete(tool.execute(tc, context))

    # 验证
    assert not result.is_error, f"DisplayCardTool 返回了错误: {result.content}"
    assert result.result_type == ToolResultType.A2UI
    template = result.content
    assert template["template_type"] == "holdings_list_card"
    assert template["asset_class"] == "ETF"
    # stock_list 被 render_holdings_list_card 转换为 holdings
    assert len(template["data"]["holdings"]) == 1
    print("   ✓ 成功从 context 读取 etf_holdings 结果")
    print(f"   ✓ template_type={template['template_type']}, asset_class={template['asset_class']}")

    # 测试未找到数据的情况
    tc_bad = ToolCall.create(name="display_card", arguments={"source_tool": "hksc_holdings"})
    result_bad = asyncio.get_event_loop().run_until_complete(tool.execute(tc_bad, context))
    assert not result_bad.is_error
    assert len(result_bad.metadata["template"]["data"]["holdings"]) == 0
    print("   ✓ 未找到数据时返回空列表卡片")

    # 测试未知工具名
    tc_unknown = ToolCall.create(name="display_card", arguments={"source_tool": "unknown_tool"})
    result_unknown = asyncio.get_event_loop().run_until_complete(tool.execute(tc_unknown, context))
    assert result_unknown.is_error
    print("   ✓ 未知工具名正确返回错误")

    print("\n" + "=" * 60)
    print("✅ DisplayCardTool 测试通过！")
    print("=" * 60)
    return True


if __name__ == "__main__":
    success1 = test_template_renderer()
    success2 = test_tool_result_carries_template()
    success3 = test_sse_event_model()
    success4 = test_display_card_tool()

    print("\n" + "=" * 60)
    all_passed = success1 and success2 and success3 and success4
    print(f"{'✅ 全部测试通过' if all_passed else '❌ 存在测试失败'}！")
    print("=" * 60)

    sys.exit(0 if all_passed else 1)

