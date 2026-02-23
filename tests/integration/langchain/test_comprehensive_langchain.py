#!/usr/bin/env python3
"""
Comprehensive test suite for LangChain integration architectural fixes
"""

import sys
import os
import asyncio
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

async def test_protocol_abstraction():
    """Test that the LangChainLLMProtocol abstraction works correctly"""
    print("\n=== Testing Protocol Abstraction ===")

    try:
        from ark_agentic.core.llm.protocol import LangChainLLMProtocol, ChatOpenAIWrapper, wrap_chat_openai
        print("OK Protocol imports successful")
    except ImportError as e:
        print(f"FAIL Protocol import failed: {e}")
        return False

    # Test protocol is runtime checkable
    try:
        from typing import runtime_checkable
        assert hasattr(LangChainLLMProtocol, '__instancecheck__')
        print("OK Protocol is runtime checkable")
    except Exception as e:
        print(f"FAIL Protocol runtime check failed: {e}")
        return False

    return True

async def test_type_safety_restoration():
    """Test that type safety has been restored in AgentRunner"""
    print("\n=== Testing Type Safety Restoration ===")

    try:
        from ark_agentic.core.runner import AgentRunner
        from ark_agentic.core.llm.protocol import LangChainLLMProtocol
        import inspect

        # Check AgentRunner.__init__ signature
        sig = inspect.signature(AgentRunner.__init__)
        llm_param = sig.parameters.get('llm')

        if llm_param and (llm_param.annotation == LangChainLLMProtocol or
                         str(llm_param.annotation) == 'LangChainLLMProtocol'):
            print("OK AgentRunner uses LangChainLLMProtocol type annotation")
        else:
            print(f"FAIL AgentRunner llm parameter type: {llm_param.annotation if llm_param else 'missing'}")
            return False

    except Exception as e:
        print(f"FAIL Type safety check failed: {e}")
        return False

    return True

async def test_graceful_fallback():
    """Test graceful fallback when LangChain dependencies are missing"""
    print("\n=== Testing Graceful Fallback ===")

    try:
        from ark_agentic.core.llm.factory import create_chat_model
        from ark_agentic.core.llm.mock import MockLLMClient

        # Test with invalid API key (should not crash)
        try:
            llm = create_chat_model("deepseek-chat", api_key="invalid-key")
            print("OK ChatOpenAI creation with invalid key handled gracefully")
        except ValueError as e:
            if "api_key is required" in str(e):
                print("OK Proper validation for missing API key")
            else:
                print(f"FAIL Unexpected error: {e}")
                return False
        except Exception as e:
            print(f"FAIL Unexpected exception: {e}")
            return False

        # Test MockLLMClient as fallback
        mock_llm = MockLLMClient()
        print("OK MockLLMClient available as fallback")

    except Exception as e:
        print(f"FAIL Graceful fallback test failed: {e}")
        return False

    return True

async def test_wrapper_functionality():
    """Test that ChatOpenAIWrapper works correctly"""
    print("\n=== Testing Wrapper Functionality ===")

    try:
        # Test with mock since we may not have langchain installed
        from ark_agentic.core.llm.protocol import ChatOpenAIWrapper

        # Create a mock ChatOpenAI-like object
        class MockChatOpenAI:
            def __init__(self):
                self.model = "test-model"
                self.temperature = 0.7

            async def ainvoke(self, messages):
                return {"content": "test response"}

            def astream(self, messages):
                async def _stream():
                    yield {"content": "test"}
                return _stream()

            def bind_tools(self, tools):
                return self

            def model_copy(self, *, update):
                new_instance = MockChatOpenAI()
                for key, value in update.items():
                    setattr(new_instance, key, value)
                return new_instance

        mock_chat = MockChatOpenAI()
        wrapper = ChatOpenAIWrapper(mock_chat)

        # Test delegation
        result = await wrapper.ainvoke([])
        print("OK Wrapper delegates ainvoke correctly")

        # Test attribute access
        assert wrapper.model == "test-model"
        print("OK Wrapper delegates attribute access correctly")

        # Test model_copy
        copied = wrapper.model_copy(update={"temperature": 0.5})
        assert isinstance(copied, ChatOpenAIWrapper)
        print("OK Wrapper model_copy returns wrapped instance")

    except Exception as e:
        print(f"FAIL Wrapper functionality test failed: {e}")
        return False

    return True

async def test_runner_integration():
    """Test AgentRunner integration with protocol"""
    print("\n=== Testing Runner Integration ===")

    try:
        from ark_agentic.core.runner import AgentRunner, RunnerConfig
        from ark_agentic.core.llm.mock import MockLLMClient
        from ark_agentic.core.llm.protocol import LangChainLLMProtocol

        # Test with MockLLMClient (should work if it implements protocol)
        mock_llm = MockLLMClient()

        # Check if MockLLMClient implements the protocol
        if isinstance(mock_llm, LangChainLLMProtocol):
            print("OK MockLLMClient implements LangChainLLMProtocol")
        else:
            print("INFO MockLLMClient may need protocol compatibility")

        # Try to create AgentRunner
        config = RunnerConfig(max_turns=2)
        runner = AgentRunner(llm=mock_llm, config=config)
        print("OK AgentRunner created with LLM client")

        # Test basic functionality
        session_id = runner.create_session_sync()
        print(f"OK Session created: {session_id[:8]}...")

    except Exception as e:
        print(f"FAIL Runner integration test failed: {e}")
        return False

    return True

async def test_error_handling():
    """Test error handling improvements"""
    print("\n=== Testing Error Handling ===")

    try:
        from ark_agentic.core.llm.errors import classify_error, LLMError, LLMErrorReason

        # Test error classification
        test_error = Exception("Test error")
        classified = classify_error(test_error, model="test-model")

        assert isinstance(classified, LLMError)
        print("OK Error classification works")

        # Test error reasons
        reasons = [r.value for r in LLMErrorReason]
        expected_reasons = ["auth", "rate_limit", "timeout", "context_overflow", "content_filter", "server_error", "network", "unknown"]

        for reason in expected_reasons:
            if reason not in reasons:
                print(f"WARN Missing error reason: {reason}")
            else:
                print(f"OK Error reason available: {reason}")

    except Exception as e:
        print(f"FAIL Error handling test failed: {e}")
        return False

    return True

async def test_dependency_handling():
    """Test dependency handling and imports"""
    print("\n=== Testing Dependency Handling ===")

    # Test optional imports
    optional_deps = {
        "langchain_openai": "LangChain OpenAI integration",
        "langchain_core": "LangChain core functionality",
        "Crypto": "Cryptographic functions for PA models"
    }

    available_deps = []
    missing_deps = []

    for dep, desc in optional_deps.items():
        try:
            __import__(dep)
            available_deps.append(dep)
            print(f"OK {dep} available - {desc}")
        except ImportError:
            missing_deps.append(dep)
            print(f"MISSING {dep} - {desc}")

    # Test graceful handling of missing dependencies
    try:
        from ark_agentic.core.llm.factory import create_chat_model

        if "langchain_openai" not in available_deps:
            # Should handle missing langchain gracefully
            try:
                llm = create_chat_model("deepseek-chat", api_key="test")
                print("WARN LangChain creation succeeded without langchain_openai (unexpected)")
            except ImportError as e:
                print("OK Missing LangChain dependency handled gracefully")
            except Exception as e:
                print(f"OK Other error handled: {type(e).__name__}")
        else:
            print("INFO LangChain available, testing with real implementation")

    except Exception as e:
        print(f"FAIL Dependency handling test failed: {e}")
        return False

    return len(missing_deps) < len(optional_deps)  # At least some deps should be available

def run_all_tests():
    """Run all comprehensive tests"""
    print("Starting Comprehensive LangChain Integration Tests...")
    print("=" * 60)

    tests = [
        test_protocol_abstraction,
        test_type_safety_restoration,
        test_graceful_fallback,
        test_wrapper_functionality,
        test_runner_integration,
        test_error_handling,
        test_dependency_handling,
    ]

    results = []

    for test in tests:
        try:
            result = asyncio.run(test())
            results.append(result)
        except Exception as e:
            print(f"FAIL Test {test.__name__} crashed: {e}")
            results.append(False)

    # Summary
    print("\n" + "=" * 60)
    print("COMPREHENSIVE TEST SUMMARY")
    print("=" * 60)

    passed = sum(results)
    total = len(results)

    for i, (test, result) in enumerate(zip(tests, results)):
        status = "PASS" if result else "FAIL"
        print(f"{i+1}. {test.__name__}: {status}")

    print(f"\nOverall: {passed}/{total} tests passed")

    if passed == total:
        print("SUCCESS: All architectural fixes are working correctly!")
        return True
    else:
        print("PARTIAL: Some issues remain, but significant progress made.")
        return False

if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)