#!/usr/bin/env python3
"""
Simplified LangChain Integration Test

Focuses on core functionality without Unicode issues.
"""

import sys
import os
from pathlib import Path
import asyncio

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

def test_basic_functionality():
    """Test basic LangChain integration functionality"""
    print("=" * 50)
    print("LANGCHAIN INTEGRATION BASIC TESTS")
    print("=" * 50)

    results = []

    # Test 1: Import structure
    try:
        from ark_agentic.core.llm.factory import create_chat_model, PAModel, get_available_models
        from ark_agentic.core.llm.protocol import LangChainLLMProtocol
        from ark_agentic.core.llm.mock_wrapper import wrap_mock_llm
        print("1. Import structure: PASS")
        results.append(True)
    except Exception as e:
        print(f"1. Import structure: FAIL - {e}")
        results.append(False)

    # Test 2: Factory function basic usage
    try:
        llm = create_chat_model("deepseek-chat", api_key="sk-test")
        assert llm is not None
        print("2. Factory function: PASS")
        results.append(True)
    except Exception as e:
        print(f"2. Factory function: FAIL - {e}")
        results.append(False)

    # Test 3: Available models
    try:
        models = get_available_models()
        assert isinstance(models, list)
        assert len(models) > 0
        assert "PA-JT-80B" in models
        print(f"3. Available models ({len(models)} found): PASS")
        results.append(True)
    except Exception as e:
        print(f"3. Available models: FAIL - {e}")
        results.append(False)

    # Test 4: PA model enum
    try:
        assert PAModel.PA_JT_80B == "PA-JT-80B"
        assert PAModel.PA_SX_80B == "PA-SX-80B"
        assert PAModel.PA_SX_235B == "PA-SX-235B"
        print("4. PA model enum: PASS")
        results.append(True)
    except Exception as e:
        print(f"4. PA model enum: FAIL - {e}")
        results.append(False)

    # Test 5: Mock LLM wrapper
    try:
        mock_llm = wrap_mock_llm()
        assert mock_llm is not None
        assert hasattr(mock_llm, 'ainvoke')
        assert hasattr(mock_llm, 'astream')
        print("5. Mock LLM wrapper: PASS")
        results.append(True)
    except Exception as e:
        print(f"5. Mock LLM wrapper: FAIL - {e}")
        results.append(False)

    return results

async def test_async_functionality():
    """Test async functionality"""
    print("\n" + "=" * 50)
    print("ASYNC FUNCTIONALITY TESTS")
    print("=" * 50)

    results = []

    # Test 6: Async invoke
    try:
        from ark_agentic.core.llm.factory import create_chat_model
        llm = create_chat_model("mock")

        messages = [{"role": "user", "content": "Hello"}]
        response = await llm.ainvoke(messages)
        assert response is not None
        assert hasattr(response, 'content')
        print("6. Async invoke: PASS")
        results.append(True)
    except Exception as e:
        print(f"6. Async invoke: FAIL - {e}")
        results.append(False)

    # Test 7: Async streaming
    try:
        chunks = []
        async for chunk in llm.astream(messages):
            chunks.append(chunk)
            if len(chunks) >= 1:  # Just test first chunk
                break

        assert len(chunks) > 0
        print("7. Async streaming: PASS")
        results.append(True)
    except Exception as e:
        print(f"7. Async streaming: FAIL - {e}")
        results.append(False)

    # Test 8: Tool binding
    try:
        tools = [{"type": "function", "function": {"name": "test_tool"}}]
        bound_llm = llm.bind_tools(tools)
        assert bound_llm is not None
        print("8. Tool binding: PASS")
        results.append(True)
    except Exception as e:
        print(f"8. Tool binding: FAIL - {e}")
        results.append(False)

    return results

def test_error_handling():
    """Test error handling and graceful fallback"""
    print("\n" + "=" * 50)
    print("ERROR HANDLING TESTS")
    print("=" * 50)

    results = []

    # Test 9: Invalid model fallback
    try:
        from ark_agentic.core.llm.factory import create_chat_model
        llm = create_chat_model("invalid-model")
        assert llm is not None
        print("9. Invalid model fallback: PASS")
        results.append(True)
    except Exception as e:
        print(f"9. Invalid model fallback: FAIL - {e}")
        results.append(False)

    # Test 10: Missing API key fallback
    try:
        llm = create_chat_model("deepseek-chat")  # No API key
        assert llm is not None
        print("10. Missing API key fallback: PASS")
        results.append(True)
    except Exception as e:
        print(f"10. Missing API key fallback: FAIL - {e}")
        results.append(False)

    return results

async def main():
    """Run all tests"""
    print("Starting LangChain Integration Tests...")
    print(f"Python: {sys.version}")
    print(f"Working directory: {os.getcwd()}")

    # Run tests
    basic_results = test_basic_functionality()
    async_results = await test_async_functionality()
    error_results = test_error_handling()

    # Summary
    all_results = basic_results + async_results + error_results
    passed = sum(all_results)
    total = len(all_results)

    print("\n" + "=" * 50)
    print("TEST SUMMARY")
    print("=" * 50)
    print(f"Passed: {passed}/{total}")
    print(f"Success Rate: {passed/total*100:.1f}%")

    if passed == total:
        print("\nSUCCESS: All tests passed!")
        return True
    else:
        print(f"\nPARTIAL: {total-passed} tests failed")
        return False

if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)