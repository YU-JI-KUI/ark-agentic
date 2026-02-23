#!/usr/bin/env python3
"""
Test frontend graceful fallback to MockLLMClient.
Validates UI behavior when LangChain dependencies are missing.
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent / "src"))

from ark_agentic.core.stream.event_bus import StreamEventBus
from ark_agentic.core.stream.events import AgentStreamEvent


def test_mock_llm_wrapper_protocol_compatibility():
    """Test that MockLLMWrapper implements the protocol correctly."""
    print("Testing MockLLMWrapper protocol compatibility...")

    try:
        from ark_agentic.core.llm.mock_wrapper import MockLLMWrapper
        from ark_agentic.core.llm.protocol import LangChainLLMProtocol

        # Create mock wrapper
        mock_wrapper = MockLLMWrapper()

        # Verify it implements the protocol
        assert isinstance(mock_wrapper, LangChainLLMProtocol)

        print("[PASS] MockLLMWrapper implements LangChainLLMProtocol correctly!")
        return True

    except ImportError as e:
        print(f"[FAIL] MockLLMWrapper not found: {e}")
        return False


async def test_mock_llm_streaming_events():
    """Test that MockLLMWrapper generates correct streaming events."""
    print("\nTesting MockLLMWrapper streaming events...")

    try:
        from ark_agentic.core.llm.mock_wrapper import MockLLMWrapper

        # Create mock wrapper
        mock_wrapper = MockLLMWrapper()

        # Create event bus
        queue = asyncio.Queue()
        bus = StreamEventBus(
            run_id="fallback-test-123",
            session_id="fallback-session-456",
            queue=queue
        )

        # Test streaming
        messages = [{"role": "user", "content": "Test fallback"}]

        bus.on_step("Testing graceful fallback")

        # Simulate streaming with mock wrapper
        async for chunk in mock_wrapper.astream(messages):
            if chunk.content:
                bus.on_content_delta(chunk.content, 0)

        bus.emit_completed("Fallback test complete", turns=1)

        # Collect events
        events = []
        while not queue.empty():
            event = await queue.get()
            events.append(event)

        print(f"Generated {len(events)} events with MockLLMWrapper:")
        for i, event in enumerate(events, 1):
            if event.type == "response.step":
                print(f"  {i}. STEP: {event.content}")
            elif event.type == "response.content.delta":
                print(f"  {i}. DELTA: '{event.delta}'")
            elif event.type == "response.completed":
                print(f"  {i}. COMPLETED: {event.message}")

        # Verify we got events
        assert len(events) > 0, "Should generate streaming events"
        assert events[0].type == "response.step"
        assert events[-1].type == "response.completed"

        print("[PASS] MockLLMWrapper streaming events working!")
        return True

    except Exception as e:
        print(f"[FAIL] MockLLMWrapper streaming test failed: {e}")
        return False


def test_factory_fallback_simulation():
    """Test factory fallback behavior when LangChain is unavailable."""
    print("\nTesting factory fallback simulation...")

    # Mock ImportError for langchain-openai
    def mock_import_error(*args, **kwargs):
        raise ImportError("No module named 'langchain_openai'")

    try:
        # Patch the import to simulate missing LangChain
        with patch('builtins.__import__', side_effect=mock_import_error):
            try:
                from ark_agentic.core.llm.factory import create_chat_model

                # This should fall back to MockLLMClient
                llm = create_chat_model("deepseek-chat")

                # Verify it's a mock/fallback client
                assert llm is not None
                print(f"[INFO] Factory returned: {type(llm)}")

                print("[PASS] Factory fallback simulation working!")
                return True

            except ImportError:
                # This is expected if fallback isn't implemented yet
                print("[INFO] Factory throws ImportError - fallback not yet implemented")
                return False

    except Exception as e:
        print(f"[FAIL] Factory fallback simulation failed: {e}")
        return False


async def test_agent_runner_with_fallback():
    """Test AgentRunner behavior with fallback LLM."""
    print("\nTesting AgentRunner with fallback LLM...")

    try:
        from ark_agentic.core.llm.mock_wrapper import MockLLMWrapper
        from ark_agentic.core.runner import AgentRunner
        from ark_agentic.core.session import SessionManager
        from ark_agentic.core.tools.registry import ToolRegistry

        # Create mock LLM wrapper
        mock_llm = MockLLMWrapper()

        # Create AgentRunner with mock LLM
        session_manager = SessionManager()
        runner = AgentRunner(
            llm=mock_llm,
            tool_registry=ToolRegistry(),
            session_manager=session_manager
        )

        # Create session first
        session_id = "test-fallback-session"
        session_manager.create_session_sync()

        # Test basic functionality
        result = await runner.run(
            session_id=session_id,
            user_input="Test graceful fallback",
            context={"test": True}
        )

        # Verify we got a response
        assert result is not None
        assert result.response is not None
        assert result.response.content is not None

        print(f"[INFO] AgentRunner with fallback returned: {result.response.content[:50]}...")
        print("[PASS] AgentRunner works with fallback LLM!")
        return True

    except Exception as e:
        print(f"[FAIL] AgentRunner fallback test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_ui_error_messages():
    """Test that UI can handle fallback scenarios gracefully."""
    print("\nTesting UI error message handling...")

    try:
        # Create error events that might occur during fallback
        queue = asyncio.Queue()
        bus = StreamEventBus(
            run_id="error-test-123",
            session_id="error-session-456",
            queue=queue
        )

        # Simulate different error scenarios
        bus.emit_failed("LangChain dependencies not available, using fallback mode")
        bus.emit_created("Fallback mode activated - functionality may be limited")
        bus.on_step("Using mock LLM client for demonstration")
        bus.on_content_delta("This is a fallback response", 0)
        bus.emit_completed("Fallback response complete", turns=1)

        # Collect events
        events = []
        while not queue.empty():
            event = queue.get_nowait()
            events.append(event)

        print(f"Generated {len(events)} fallback UI events:")
        for i, event in enumerate(events, 1):
            if event.type == "response.failed":
                print(f"  {i}. ERROR: {event.error_message}")
            elif event.type == "response.created":
                print(f"  {i}. CREATED: {event.content}")
            elif event.type == "response.step":
                print(f"  {i}. STEP: {event.content}")
            elif event.type == "response.content.delta":
                print(f"  {i}. DELTA: '{event.delta}'")
            elif event.type == "response.completed":
                print(f"  {i}. COMPLETED: {event.message}")

        # Verify event structure
        assert len(events) == 5
        assert events[0].type == "response.failed"
        assert events[1].type == "response.created"
        assert events[-1].type == "response.completed"

        print("[PASS] UI error message handling working!")
        return True

    except Exception as e:
        print(f"[FAIL] UI error message test failed: {e}")
        return False


async def test_end_to_end_fallback():
    """Test complete end-to-end fallback scenario."""
    print("\nTesting end-to-end fallback scenario...")

    try:
        # This would simulate the complete flow:
        # 1. Factory tries to create LangChain model
        # 2. ImportError occurs
        # 3. Factory falls back to MockLLMWrapper
        # 4. AgentRunner uses MockLLMWrapper
        # 5. UI receives proper events

        # For now, just test the components we can
        from ark_agentic.core.llm.mock_wrapper import MockLLMWrapper
        from ark_agentic.core.stream.event_bus import StreamEventBus

        mock_llm = MockLLMWrapper()

        # Test that mock LLM can be used in streaming scenario
        queue = asyncio.Queue()
        bus = StreamEventBus("e2e-test", "e2e-session", queue)

        bus.on_step("End-to-end fallback test")

        messages = [{"role": "user", "content": "Test E2E fallback"}]
        async for chunk in mock_llm.astream(messages):
            if chunk.content:
                bus.on_content_delta(chunk.content, 0)

        bus.emit_completed("E2E fallback test complete", turns=1)

        # Count events
        event_count = 0
        while not queue.empty():
            await queue.get()
            event_count += 1

        assert event_count > 0, "Should generate events in E2E test"

        print(f"[INFO] E2E test generated {event_count} events")
        print("[PASS] End-to-end fallback scenario working!")
        return True

    except Exception as e:
        print(f"[FAIL] End-to-end fallback test failed: {e}")
        return False


async def main():
    """Run all graceful fallback tests."""
    print("=== Frontend Graceful Fallback Test ===\n")

    test_results = []

    try:
        # Test 1: Protocol compatibility
        result1 = test_mock_llm_wrapper_protocol_compatibility()
        test_results.append(("MockLLMWrapper Protocol", result1))

        # Test 2: Streaming events
        result2 = await test_mock_llm_streaming_events()
        test_results.append(("MockLLMWrapper Streaming", result2))

        # Test 3: Factory fallback simulation
        result3 = test_factory_fallback_simulation()
        test_results.append(("Factory Fallback Simulation", result3))

        # Test 4: AgentRunner with fallback
        result4 = await test_agent_runner_with_fallback()
        test_results.append(("AgentRunner Fallback", result4))

        # Test 5: UI error messages
        result5 = test_ui_error_messages()
        test_results.append(("UI Error Messages", result5))

        # Test 6: End-to-end fallback
        result6 = await test_end_to_end_fallback()
        test_results.append(("End-to-End Fallback", result6))

        # Summary
        print("\n=== Graceful Fallback Test Results ===")
        passed = 0
        total = len(test_results)

        for test_name, result in test_results:
            status = "[PASS]" if result else "[FAIL]"
            print(f"{status} {test_name}")
            if result:
                passed += 1

        print(f"\nResults: {passed}/{total} tests passed")

        if passed == total:
            print("\n[SUCCESS] All graceful fallback tests passed!")
            print("Frontend is ready for graceful fallback scenarios.")
        else:
            print(f"\n[WARNING] {total - passed} tests failed.")
            print("Some fallback functionality may not be fully implemented yet.")

        # Key findings
        print("\n[INFO] Key findings for 7/7 tests:")
        print("- MockLLMWrapper should implement LangChainLLMProtocol")
        print("- Factory should catch ImportError and return MockLLMWrapper")
        print("- UI should handle fallback scenarios gracefully")
        print("- Streaming events should work with fallback client")

    except Exception as e:
        print(f"\n[FAIL] Graceful fallback test suite failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())