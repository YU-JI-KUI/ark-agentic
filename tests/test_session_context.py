"""
测试 Session 上下文注入
"""

import asyncio
import os
import sys

# 添加 src 到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


async def test_session_context():
    """测试会话上下文注入功能"""
    print("=" * 60)
    print("测试 Session 上下文注入")
    print("=" * 60)
    
    # 设置环境变量
    os.environ["SECURITIES_SERVICE_MOCK"] = "true"
    os.environ["LLM_PROVIDER"] = "deepseek"
    os.environ["DEEPSEEK_API_KEY"] = "test_key"
    
    try:
        # 1. 测试 SessionManager 上下文方法
        print("\n1. 测试 SessionManager 上下文方法...")
        from ark_agentic.core.session import SessionManager
        
        session_manager = SessionManager(enable_persistence=False)
        session = session_manager.create_session_sync()
        session_id = session.session_id
        
        # 设置上下文
        session_manager.set_context(session_id, "account_type", "margin")
        session_manager.set_context(session_id, "user_id", "U002")
        session_manager.set_context(session_id, "risk_level", "high")
        
        # 获取单个上下文
        account_type = session_manager.get_context(session_id, "account_type")
        assert account_type == "margin", f"Expected 'margin', got '{account_type}'"
        print(f"   ✓ set_context/get_context 工作正常")
        
        # 获取所有上下文
        all_context = session_manager.get_all_context(session_id)
        assert len(all_context) == 3, f"Expected 3 context items, got {len(all_context)}"
        assert all_context["account_type"] == "margin"
        assert all_context["user_id"] == "U002"
        assert all_context["risk_level"] == "high"
        print(f"   ✓ get_all_context 返回正确: {all_context}")
        
        # 2. 测试 AgentRunner 系统提示注入
        print("\n2. 测试 AgentRunner 系统提示注入...")
        from ark_agentic.core.runner import AgentRunner, RunnerConfig
        from ark_agentic.core.llm import create_llm_client
        from ark_agentic.core.tools.registry import ToolRegistry
        from ark_agentic.core.prompt.builder import PromptConfig
        
        # 创建 Mock LLM 客户端
        llm_client = create_llm_client(provider="mock")
        
        # 创建 Runner
        runner = AgentRunner(
            llm_client=llm_client,
            tool_registry=ToolRegistry(),
            session_manager=session_manager,
            config=RunnerConfig(
                prompt_config=PromptConfig(
                    agent_name="证券助手",
                    agent_description="专业的证券资产管理助手",
                    custom_instructions="你是一个证券助手。"
                )
            ),
        )
        
        # 构建系统提示
        system_prompt = runner._build_system_prompt(
            context={},
            session_id=session_id
        )
        
        # 验证上下文已注入
        assert "当前会话上下文" in system_prompt, "系统提示中应包含上下文块"
        assert "account_type" in system_prompt, "系统提示中应包含 account_type"
        assert "margin" in system_prompt, "系统提示中应包含 margin 值"
        assert "user_id" in system_prompt, "系统提示中应包含 user_id"
        assert "U002" in system_prompt, "系统提示中应包含 U002 值"
        
        print(f"   ✓ 系统提示已注入上下文")
        print(f"\n   系统提示片段:")
        # 提取上下文部分
        if "## 当前会话上下文" in system_prompt:
            context_part = system_prompt.split("## 当前会话上下文")[1][:200]
            print(f"   {context_part.strip()[:150]}...")
        
        # 3. 测试上下文持久化
        print("\n3. 测试上下文持久化...")
        metadata = session_manager.get_metadata(session_id)
        assert "context.account_type" in metadata
        assert "context.user_id" in metadata
        assert metadata["context.account_type"] == "margin"
        print(f"   ✓ 上下文已正确存储在 metadata 中")
        
        print("\n" + "=" * 60)
        print("✅ 所有测试通过！")
        print("=" * 60)
        
        print("\n📋 功能验证:")
        print("  ✓ SessionManager.set_context() 工作正常")
        print("  ✓ SessionManager.get_context() 工作正常")
        print("  ✓ SessionManager.get_all_context() 工作正常")
        print("  ✓ AgentRunner 自动注入上下文到系统提示")
        print("  ✓ 上下文持久化到 metadata")
        
        return True
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = asyncio.run(test_session_context())
    sys.exit(0 if success else 1)
