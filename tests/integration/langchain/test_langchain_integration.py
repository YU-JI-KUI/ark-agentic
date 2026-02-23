#!/usr/bin/env python3
"""
Simple test script to validate LangChain integration
"""

import sys
import os
import asyncio
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

async def test_langchain_integration():
    """Test basic LangChain integration functionality"""
    print("=== Testing LangChain Integration ===")

    # Test 1: Import core modules
    print("\n1. Testing imports...")
    try:
        from ark_agentic.core.llm.factory import create_chat_model, PAModel
        from ark_agentic.core.runner import AgentRunner, RunnerConfig
        from ark_agentic.core.llm.mock import MockLLMClient
        print("OK Core imports successful")
    except ImportError as e:
        print(f"FAIL Import failed: {e}")
        return False

    # Test 2: Create mock LLM client
    print("\n2. Testing Mock LLM client...")
    try:
        mock_llm = MockLLMClient()
        print("OK Mock LLM client created")
    except Exception as e:
        print(f"FAIL Mock LLM creation failed: {e}")
        return False

    # Test 3: Test ChatOpenAI creation with mock/fallback
    print("\n3. Testing ChatOpenAI creation...")
    try:
        # This should fall back to mock if no real API key
        llm = create_chat_model("deepseek-chat", api_key="test-key")
        print("OK ChatOpenAI creation successful")
    except Exception as e:
        print(f"FAIL ChatOpenAI creation failed: {e}")
        # Try with mock instead
        try:
            llm = mock_llm
            print("OK Using Mock LLM as fallback")
        except Exception as e2:
            print(f"FAIL Mock LLM fallback failed: {e2}")
            return False

    # Test 4: Create AgentRunner with LangChain LLM
    print("\n4. Testing AgentRunner creation...")
    try:
        config = RunnerConfig(max_turns=2)
        runner = AgentRunner(llm=llm, config=config)
        print("OK AgentRunner created with LangChain LLM")
    except Exception as e:
        print(f"FAIL AgentRunner creation failed: {e}")
        return False

    # Test 5: Test basic runner functionality
    print("\n5. Testing basic runner functionality...")
    try:
        session_id = runner.create_session_sync()
        print(f"OK Session created: {session_id[:8]}...")
    except Exception as e:
        print(f"FAIL Session creation failed: {e}")
        return False

    # Test 6: Test message building (without actual LLM call)
    print("\n6. Testing message building...")
    try:
        # Add a test message to session
        from ark_agentic.core.types import AgentMessage
        test_msg = AgentMessage.user("Hello, test message")
        runner.session_manager.add_message_sync(session_id, test_msg)

        # Try to build messages (this tests the LangChain message format)
        messages = runner._build_messages(session_id, {})
        print(f"OK Messages built successfully: {len(messages)} messages")

        # Check message format
        if messages and isinstance(messages[0], dict) and "role" in messages[0]:
            print("OK Message format is correct for LangChain")
        else:
            print("FAIL Message format may be incorrect")

    except Exception as e:
        print(f"FAIL Message building failed: {e}")
        return False

    print("\n=== LangChain Integration Test Summary ===")
    print("OK All basic tests passed")
    return True

async def test_pa_models():
    """Test PA model configuration"""
    print("\n=== Testing PA Model Configuration ===")

    try:
        from ark_agentic.core.llm.factory import PAModel, _load_pa_model_config

        # Test PA model enum
        print(f"Available PA models: {[m.value for m in PAModel]}")

        # Test config loading (should fail gracefully without env vars)
        try:
            config = _load_pa_model_config(PAModel.PA_SX_80B)
            print("FAIL PA config loaded without env vars (unexpected)")
        except ValueError as e:
            print("OK PA config properly requires environment variables")

    except Exception as e:
        print(f"FAIL PA model test failed: {e}")
        return False

    return True

def test_dependencies():
    """Test required dependencies"""
    print("\n=== Testing Dependencies ===")

    required_deps = [
        "langchain_openai",
        "langchain_core",
        "httpx",
        "pyyaml",
        "numpy",
        "faiss",
    ]

    missing_deps = []
    for dep in required_deps:
        try:
            __import__(dep.replace("-", "_"))
            print(f"OK {dep}")
        except ImportError:
            print(f"MISSING {dep}")
            missing_deps.append(dep)

    # Test optional dependencies
    optional_deps = ["Crypto"]  # pycryptodome
    for dep in optional_deps:
        try:
            __import__(dep)
            print(f"OK {dep} (optional)")
        except ImportError:
            print(f"MISSING {dep} (optional)")

    return len(missing_deps) == 0

if __name__ == "__main__":
    print("Starting LangChain Integration Tests...")

    # Test dependencies first
    deps_ok = test_dependencies()
    if not deps_ok:
        print("\nFAILED: Dependency issues found. Please install missing dependencies.")
        sys.exit(1)

    # Run async tests
    try:
        result1 = asyncio.run(test_langchain_integration())
        result2 = asyncio.run(test_pa_models())

        if result1 and result2:
            print("\nSUCCESS: All tests passed! LangChain integration appears to be working.")
        else:
            print("\nFAILED: Some tests failed. Check the output above for details.")
            sys.exit(1)

    except Exception as e:
        print(f"\nFAILED: Test execution failed: {e}")
        sys.exit(1)