"""
测试 SSE 模板事件

验证模板数据通过 tool_results.metadata.template 传递到前端的流程。
"""

import asyncio
import json
import sys


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
    assert template["template"] == "queryAccountAssetResultTpl"
    assert template["data"]["assetData"]["totalAssetVal"] == "1250000.50"
    print(f"   ✓ template={template['template']}")

    # 测试 2: holdings_list_card
    print("\n2. 测试 holdings_list_card...")
    data = {
        "holdings": [{"code": "510300", "name": "沪深300ETF"}],
        "summary": {"total_value": "48000"},
    }
    template = TemplateRenderer.render_holdings_list_card("ETF", data)
    assert template["template"] == "holdings_list_card"
    assert template["asset_class"] == "ETF"
    assert len(template["data"]["holdings"]) == 1
    print(f"   ✓ template={template['template']}, asset_class={template['asset_class']}")

    # 测试 3: cash_assets_card
    print("\n3. 测试 cash_assets_card...")
    data = {"available_cash": "50000", "frozen_cash": "0", "total_cash": "50000"}
    template = TemplateRenderer.render_cash_assets_card(data)
    assert template["template"] == "cash_assets_card"
    print(f"   ✓ template={template['template']}")

    # 测试 4: security_detail_card
    print("\n4. 测试 security_detail_card...")
    data = {"security_code": "510300", "security_name": "沪深300ETF"}
    template = TemplateRenderer.render_security_detail_card(data)
    assert template["template"] == "security_detail_card"
    print(f"   ✓ template={template['template']}")

    print("\n" + "=" * 60)
    print("✅ TemplateRenderer 测试通过！")
    print("=" * 60)


def test_tool_result_carries_template():
    """测试工具结果通过 metadata.template 携带模板数据"""
    print("\n" + "=" * 60)
    print("测试工具结果携带模板数据")
    print("=" * 60)

    from ark_agentic.core.types import AgentToolResult

    # 模拟工具返回（与 etf_holdings.py 等工具的实际行为一致）
    template = {
        "template": "holdings_list_card",
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
    assert result.metadata["template"]["template"] == "holdings_list_card"
    print("   ✓ metadata.template 存在且 template 键正确")

    # 验证模板提取逻辑（与 app.py run_agent() 中的逻辑一致）
    extracted = result.metadata.get("template") if result.metadata else None
    assert extracted is not None
    assert isinstance(extracted, dict) and "template" in extracted
    print("   ✓ 模板提取逻辑验证通过")

    print("\n" + "=" * 60)
    print("✅ 工具结果模板测试通过！")
    print("=" * 60)


def test_sse_event_model():
    """测试 SSE 事件模型可以正确携带模板数据"""
    print("\n" + "=" * 60)
    print("测试 SSE 事件模型")
    print("=" * 60)

    from ark_agentic.api.models import SSEEvent

    template = {
        "template": "queryAccountAssetResultTpl",
        "data": {"assetData": {"totalAssetVal": "1000000.00"}},
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
    assert parsed["template"]["template"] == "queryAccountAssetResultTpl"
    print(f"   ✓ SSE event type={parsed['type']}")
    print(f"   ✓ template={parsed['template']['template']}")

    print("\n" + "=" * 60)
    print("✅ SSE 事件模型测试通过！")
    print("=" * 60)


def test_display_card_tool():
    """测试 RenderA2UITool preset 模式从 context 读取数据工具结果并渲染卡片"""
    print("\n" + "=" * 60)
    print("测试 RenderA2UITool (preset mode)")
    print("=" * 60)

    from ark_agentic.core.types import ToolCall, ToolResultType
    from ark_agentic.agents.securities.a2ui import SECURITIES_PRESETS
    from ark_agentic.core.tools.render_a2ui import RenderA2UITool

    etf_data = {
        "stock_list": [{"secuCode": "510300", "secuName": "沪深300ETF", "mktVal": 48000}],
        "total_market_value": 48000,
        "total_profit": 3000,
        "total": 1,
    }

    context = {
        "etf_holdings": etf_data,
        "user_id": "U001",
    }

    tool = RenderA2UITool(preset=SECURITIES_PRESETS, group="securities")
    tc = ToolCall.create(name="render_a2ui", arguments={"preset_type": "etf_holdings"})

    result = asyncio.get_event_loop().run_until_complete(tool.execute(tc, context))

    assert not result.is_error, f"RenderA2UITool 返回了错误: {result.content}"
    assert result.result_type == ToolResultType.A2UI
    template = result.content
    assert template["template"] == "holdings_list_card"
    assert template["asset_class"] == "ETF"
    assert len(template["data"]["holdings"]) == 1
    print("   ✓ 成功从 context 读取 etf_holdings 结果")
    print(f"   ✓ template={template['template']}, asset_class={template['asset_class']}")

    # 未找到数据 — extractor 返回 error 键
    tc_bad = ToolCall.create(name="render_a2ui", arguments={"preset_type": "hksc_holdings"})
    result_bad = asyncio.get_event_loop().run_until_complete(tool.execute(tc_bad, context))
    assert not result_bad.is_error  # preset extractor returns data with error key, not tool error
    assert "error" in result_bad.content or "未找到" in str(result_bad.content)
    print("   ✓ 未找到数据时 extractor 返回带 error 的 payload")

    # 未注册的 preset_type — tool 返回错误
    tc_unknown = ToolCall.create(name="render_a2ui", arguments={"preset_type": "unknown_tool"})
    result_unknown = asyncio.get_event_loop().run_until_complete(tool.execute(tc_unknown, context))
    assert result_unknown.is_error
    print("   ✓ 未知 preset_type 正确返回错误")

    print("\n" + "=" * 60)
    print("✅ RenderA2UITool preset 模式测试通过！")
    print("=" * 60)


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

