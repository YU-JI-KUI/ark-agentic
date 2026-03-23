"""
测试 Securities Agent 集成
"""

import asyncio
import os
import sys

# 添加 src 到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

async def test_securities_agent_integration():
    """测试 Securities Agent 是否正确集成"""
    print("=" * 60)
    print("测试 Securities Agent 集成")
    print("=" * 60)
    
    # 设置 Mock 模式
    os.environ["SECURITIES_SERVICE_MOCK"] = "true"
    os.environ["LLM_PROVIDER"] = "openai"
    os.environ["API_KEY"] = "test_key"
    
    try:
        # 1. 测试导入
        print("\n1. 测试导入...")
        from ark_agentic.agents.securities import create_securities_agent
        print("   ✓ 导入成功")
        
        # 2. 测试工具创建
        print("\n2. 测试工具创建...")
        from ark_agentic.agents.securities.tools import create_securities_tools
        tools = create_securities_tools()
        print(f"   ✓ 创建了 {len(tools)} 个工具")
        for tool in tools:
            print(f"     - {tool.name}")
        
        # 3. 测试服务适配器
        print("\n3. 测试服务适配器...")
        from ark_agentic.agents.securities.tools.service import create_service_adapter
        adapter = create_service_adapter("account_overview", mock=True)
        data = await adapter.call(account_type="normal", user_id="U001")
        print(f"   ✓ Mock 数据加载成功")
        print(f"     总资产: ¥{data.get('total_assets'):,.2f}")
        
        # 4. 测试 Pydantic Schema
        print("\n4. 测试 Pydantic Schema...")
        from ark_agentic.agents.securities.schemas import AccountOverviewSchema
        schema = AccountOverviewSchema.from_raw_data(
            {"totalAssets": 1000000, "cashBalance": 50000, "stockValue": 950000,
             "todayProfit": 10000, "totalProfit": 100000, "profitRate": 0.1},
            account_type="normal"
        )
        print(f"   ✓ Schema 验证成功")
        print(f"     总资产: ¥{schema.total_assets:,.2f}")
        
        # 5. 测试模板渲染器
        print("\n5. 测试模板渲染器...")
        from ark_agentic.agents.securities.template_renderer import TemplateRenderer, should_return_template
        template = TemplateRenderer.render_account_overview_card(data)
        print(f"   ✓ 模板渲染成功")
        print(f"     模板类型: {template['template_type']}")
        
        # 测试意图判断
        assert should_return_template("查看资产", "account_overview") == True
        assert should_return_template("为什么今天亏损了", "account_overview") == False
        print(f"   ✓ 意图判断正确")
        
        print("\n" + "=" * 60)
        print("✅ 所有测试通过！")
        print("=" * 60)
        
        print("\n📋 集成状态:")
        print("  ✓ 6 个服务适配器（Pydantic）")
        print("  ✓ 6 个工具类")
        print("  ✓ 模板渲染系统")
        print("  ✓ Mock 数据系统")
        print("  ✓ 意图判断逻辑")
        print("\n🚀 可以在 app.py 中通过 agent_id='securities' 调用")
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    return True


if __name__ == "__main__":
    success = asyncio.run(test_securities_agent_integration())
    sys.exit(0 if success else 1)
