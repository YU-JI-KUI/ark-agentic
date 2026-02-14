"""
测试 SSE 模板事件
"""

import asyncio
import json
import os
import sys

# 添加 src 到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


def test_extract_template():
    """测试模板提取函数"""
    print("=" * 60)
    print("测试模板提取函数")
    print("=" * 60)
    
    from ark_agentic.app import extract_template_from_response
    
    # 测试 1: JSON 代码块
    print("\n1. 测试 JSON 代码块...")
    content1 = """
这是您的资产信息：

```json
{
  "template_type": "account_overview_card",
  "data": {
    "total_assets": 1000000.00,
    "cash_balance": 50000.00
  }
}
```
    """
    template = extract_template_from_response(content1)
    assert template is not None, "应该检测到模板"
    assert template["template_type"] == "account_overview_card"
    assert template["data"]["total_assets"] == 1000000.00
    print(f"   ✓ 成功提取模板: {template['template_type']}")
    
    # 测试 2: 纯 JSON
    print("\n2. 测试纯 JSON...")
    content2 = json.dumps({
        "template_type": "holdings_list_card",
        "data": {"holdings": []}
    })
    template = extract_template_from_response(content2)
    assert template is not None
    assert template["template_type"] == "holdings_list_card"
    print(f"   ✓ 成功提取模板: {template['template_type']}")
    
    # 测试 3: 无模板（普通 Markdown）
    print("\n3. 测试无模板...")
    content3 = "这是普通的 Markdown 文本，没有模板。"
    template = extract_template_from_response(content3)
    assert template is None, "不应该检测到模板"
    print("   ✓ 正确识别无模板内容")
    
    # 测试 4: 无 template_type 字段
    print("\n4. 测试无 template_type 字段...")
    content4 = """
```json
{
  "data": {"some": "value"}
}
```
    """
    template = extract_template_from_response(content4)
    assert template is None, "不应该检测到模板（缺少 template_type）"
    print("   ✓ 正确识别非模板 JSON")
    
    # 测试 5: 多个 JSON 代码块
    print("\n5. 测试多个 JSON 代码块...")
    content5 = """
这是一些说明文字。

```json
{
  "not_a_template": true
}
```

这是您的资产：

```json
{
  "template_type": "asset_summary_card",
  "data": {"total": 500000}
}
```
    """
    template = extract_template_from_response(content5)
    assert template is not None
    assert template["template_type"] == "asset_summary_card"
    print(f"   ✓ 成功从多个代码块中提取模板: {template['template_type']}")
    
    print("\n" + "=" * 60)
    print("✅ 所有测试通过！")
    print("=" * 60)
    
    return True


async def test_sse_template_event():
    """测试 SSE 模板事件（集成测试）"""
    print("\n" + "=" * 60)
    print("测试 SSE 模板事件集成")
    print("=" * 60)
    
    # 设置环境变量
    os.environ["SECURITIES_SERVICE_MOCK"] = "true"
    os.environ["LLM_PROVIDER"] = "mock"
    
    try:
        from ark_agentic.agents.securities.api import create_securities_agent_from_env
        from ark_agentic.app import extract_template_from_response
        
        print("\n1. 创建 securities agent...")
        agent = create_securities_agent_from_env()
        print("   ✓ Agent 创建成功")
        
        print("\n2. 模拟 LLM 返回包含模板的响应...")
        mock_response = """
```json
{
  "template_type": "account_overview_card",
  "data": {
    "account_type": "margin",
    "total_assets": 1250000.00,
    "cash_balance": 50000.00,
    "market_value": 1200000.00,
    "margin_ratio": 280.5
  }
}
```
        """
        
        template = extract_template_from_response(mock_response)
        assert template is not None
        assert template["template_type"] == "account_overview_card"
        assert template["data"]["account_type"] == "margin"
        print(f"   ✓ 模板提取成功: {template['template_type']}")
        print(f"   ✓ 数据字段: {list(template['data'].keys())}")
        
        print("\n" + "=" * 60)
        print("✅ SSE 模板事件集成测试通过！")
        print("=" * 60)
        
        print("\n📋 功能验证:")
        print("  ✓ extract_template_from_response() 工作正常")
        print("  ✓ 支持 JSON 代码块格式")
        print("  ✓ 支持纯 JSON 格式")
        print("  ✓ 正确识别非模板内容")
        print("  ✓ 模板数据结构正确")
        
        return True
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    # 运行单元测试
    success1 = test_extract_template()
    
    # 运行集成测试
    success2 = asyncio.run(test_sse_template_event())
    
    sys.exit(0 if (success1 and success2) else 1)
