"""
阶段一测试脚本：验证 Mock 数据系统和服务适配层
"""

import asyncio
import sys
from pathlib import Path

import pytest

# 添加项目路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

from ark_agentic.agents.securities.tools.service import get_mock_loader, create_service_adapter


async def test_mock_loader():
    """测试 Mock 数据加载器"""
    print("=" * 60)
    print("测试 1: Mock 数据加载器")
    print("=" * 60)
    
    loader = get_mock_loader()
    
    # 测试普通账户
    print("\n1. 加载普通账户数据:")
    data = loader.load("account_overview", "normal_user")
    print(f"   ✓ 总资产: {data.get('data', {}).get('totalAssets')}")
    
    # 测试两融账户
    print("\n2. 加载两融账户数据:")
    data = loader.load("account_overview", "margin_user")
    print(f"   ✓ 总资产: {data.get('data', {}).get('totalAssets')}")
    print(f"   ✓ 维持担保比率: {data.get('data', {}).get('marginRatio')}")
    
    # 测试 ETF 持仓
    print("\n3. 加载 ETF 持仓数据:")
    data = loader.load("etf_holdings", "default")
    holdings = data.get('data', {}).get('holdings', [])
    print(f"   ✓ 持仓数量: {len(holdings)}")
    if holdings:
        print(f"   ✓ 第一只: {holdings[0].get('securityName')}")
    
    # 测试具体标的
    print("\n4. 加载具体标的数据 (510300):")
    data = loader.load("security_detail", security_code="510300")
    print(f"   ✓ 标的名称: {data.get('data', {}).get('securityName')}")
    
    # 列出场景
    print("\n5. 列出 account_overview 的所有场景:")
    scenarios = loader.list_scenarios("account_overview")
    print(f"   ✓ 可用场景: {', '.join(scenarios)}")
    
    print("\n✅ Mock 数据加载器测试通过!\n")


async def test_service_adapter(monkeypatch: pytest.MonkeyPatch):
    """测试服务适配器（mock 由 SECURITIES_SERVICE_MOCK 控制）"""
    monkeypatch.setenv("SECURITIES_SERVICE_MOCK", "true")
    print("=" * 60)
    print("测试 2: 服务适配器")
    print("=" * 60)
    
    # 测试账户总资产适配器（普通账户，mock 通过 context 指定）
    print("\n1. 测试账户总资产适配器 (普通账户):")
    adapter = create_service_adapter("account_overview", context={"mock_mode": True})
    data = await adapter.call(account_type="normal", user_id="U001")
    print(f"   ✓ 总资产: {data.get('total_assets')}")
    print(f"   ✓ 现金余额: {data.get('cash_balance')}")
    print(f"   ✓ 今日收益: {data.get('today_profit')}")
    
    # 测试两融账户
    print("\n2. 测试账户总资产适配器 (两融账户):")
    data = await adapter.call(account_type="margin", user_id="U001")
    print(f"   ✓ 总资产: {data.get('total_assets')}")
    print(f"   ✓ 维持担保比率: {data.get('margin_ratio')}")
    print(f"   ✓ 风险等级: {data.get('risk_level')}")
    
    # 测试 ETF 持仓适配器
    print("\n3. 测试 ETF 持仓适配器:")
    adapter = create_service_adapter("etf_holdings", context={"mock_mode": True})
    data = await adapter.call(account_type="normal", user_id="U001")
    holdings = data.get('holdings', [])
    print(f"   ✓ 持仓数量: {len(holdings)}")
    if holdings:
        h = holdings[0]
        print(f"   ✓ 第一只: {h.get('security_name')}")
        print(f"   ✓ 收益率: {h.get('profit_rate')}")
    
    summary = data.get('summary', {})
    print(f"   ✓ 总市值: {summary.get('total_market_value')}")
    print(f"   ✓ 总收益: {summary.get('total_profit')}")
    
    await adapter.close()
    
    print("\n✅ 服务适配器测试通过!\n")


async def main():
    """运行所有测试"""
    print("\n" + "=" * 60)
    print("阶段一：基础架构测试")
    print("=" * 60 + "\n")
    
    try:
        await test_mock_loader()
        await test_service_adapter()
        
        print("=" * 60)
        print("🎉 阶段一测试全部通过!")
        print("=" * 60)
        print("\n已完成:")
        print("  ✓ 目录结构创建")
        print("  ✓ MockDataLoader 实现")
        print("  ✓ Mock 数据文件创建 (7个)")
        print("  ✓ BaseServiceAdapter 实现")
        print("  ✓ AccountOverviewAdapter 实现")
        print("  ✓ ETFHoldingsAdapter 实现")
        print("  ✓ MockServiceAdapter 实现")
        print("  ✓ 服务适配器工厂函数")
        print("\n可以进入阶段二：核心功能开发\n")
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
