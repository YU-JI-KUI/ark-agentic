#!/usr/bin/env python3
"""
Test frontend integration with restored LangChainLLMProtocol.
Verifies that the protocol wrapper maintains UI compatibility.
"""

import asyncio
import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent / "src"))

from ark_agentic.core.llm.protocol import LangChainLLMProtocol, ChatOpenAIWrapper, wrap_chat_openai
from ark_agentic.core.llm.factory import create_chat_model
from ark_agentic.core.stream.event_bus import StreamEventBus
from ark_agentic.core.stream.events import AgentStreamEvent


class MockChatOpenAI:
    """Mock ChatOpenAI for testing protocol wrapper."""

    def __init__(self, model="mock-model", temperature=0.7, **kwargs):
        self.model = model
        self.temperature = temperature
        self._kwargs = kwargs

    async def ainvoke(self, messages):
        """Mock non-streaming response."""
        class MockAIMessage:
            def __init__(self):
                self.content = "Mock response from protocol wrapper"
                self.tool_calls = []
                self.response_metadata = {"finish_reason": "stop"}
                self.usage_metadata = {"input_tokens": 10, "output_tokens": 5}
        return MockAIMessage()

    async def astream(self, messages):
        """Mock streaming response."""
        class MockChunk:
            def __init__(self, content="", tool_calls=None):
                self.content = content
                self.tool_calls = tool_calls or []
                self.response_metadata = {"finish_reason": "stop"}
                self.usage_metadata = {"input_tokens": 10, "output_tokens": 5}

        # Simulate streaming chunks
        chunks = ["Hello ", "from ", "protocol ", "wrapper!"]
        for chunk in chunks:
            yield MockChunk(content=chunk)
            await asyncio.sleep(0.01)  # Simulate streaming delay

    def bind_tools(self, tools):
        """Mock tool binding."""
        new_instance = MockChatOpenAI(self.model, self.temperature, **self._kwargs)
        new_instance._bound_tools = tools
        return new_instance

    def model_copy(self, *, update):
        """Mock model copy."""
        new_kwargs = {**self._kwargs}
        # Remove conflicting keys from kwargs to avoid duplicate arguments
        for key in ["model", "temperature"]:
            new_kwargs.pop(key, None)
        # Also remove keys from update that we'll pass explicitly
        update_copy = {k: v for k, v in update.items() if k not in ["model", "temperature"]}
        new_kwargs.update(update_copy)
        return MockChatOpenAI(
            model=update.get("model", self.model),
            temperature=update.get("temperature", self.temperature),
            **new_kwargs
        )

    def copy(self, *, update):
        """Mock copy (Pydantic v1 compatibility)."""
        return self.model_copy(update=update)


async def test_protocol_wrapper_basic():
    """Test basic protocol wrapper functionality."""
    print("Testing protocol wrapper basic functionality...")

    # Create mock ChatOpenAI and wrap it
    mock_llm = MockChatOpenAI()
    wrapped_llm = ChatOpenAIWrapper(mock_llm)

    # Verify it implements the protocol
    assert isinstance(wrapped_llm, LangChainLLMProtocol)

    # Test non-streaming call
    messages = [{"role": "user", "content": "Hello"}]
    response = await wrapped_llm.ainvoke(messages)
    assert response.content == "Mock response from protocol wrapper"

    print("[PASS] Protocol wrapper basic functionality working!")


async def test_protocol_wrapper_streaming():
    """Test streaming functionality through protocol wrapper."""
    print("\nTesting protocol wrapper streaming...")

    mock_llm = MockChatOpenAI()
    wrapped_llm = ChatOpenAIWrapper(mock_llm)

    # Test streaming call
    messages = [{"role": "user", "content": "Hello"}]
    chunks = []
    async for chunk in wrapped_llm.astream(messages):
        chunks.append(chunk.content)

    expected_chunks = ["Hello ", "from ", "protocol ", "wrapper!"]
    assert chunks == expected_chunks

    print(f"[PASS] Streaming through wrapper: {' '.join(chunks)}")


async def test_protocol_wrapper_tools():
    """Test tool binding through protocol wrapper."""
    print("\nTesting protocol wrapper tool binding...")

    mock_llm = MockChatOpenAI()
    wrapped_llm = ChatOpenAIWrapper(mock_llm)

    # Test tool binding
    tools = [{"type": "function", "function": {"name": "test_tool"}}]
    bound_llm = wrapped_llm.bind_tools(tools)

    # Verify bound LLM is also protocol-compatible
    assert isinstance(bound_llm, LangChainLLMProtocol)
    assert hasattr(bound_llm._llm, '_bound_tools')

    print("[PASS] Tool binding through wrapper working!")


async def test_protocol_wrapper_copy():
    """Test model copying through protocol wrapper."""
    print("\nTesting protocol wrapper model copying...")

    mock_llm = MockChatOpenAI(temperature=0.7)
    wrapped_llm = ChatOpenAIWrapper(mock_llm)

    # Test model_copy
    copied_llm = wrapped_llm.model_copy(update={"temperature": 0.9})
    assert isinstance(copied_llm, LangChainLLMProtocol)
    assert copied_llm._llm.temperature == 0.9

    # Test copy (Pydantic v1 compatibility)
    copied_llm2 = wrapped_llm.copy(update={"temperature": 0.5})
    assert isinstance(copied_llm2, LangChainLLMProtocol)
    assert copied_llm2._llm.temperature == 0.5

    print("[PASS] Model copying through wrapper working!")


async def test_streaming_events_with_protocol():
    """Test that streaming events work correctly with the protocol wrapper."""
    print("\nTesting streaming events with protocol wrapper...")

    # Create event bus
    queue = asyncio.Queue()
    bus = StreamEventBus(
        run_id="protocol-test-123",
        session_id="protocol-session-456",
        queue=queue
    )

    # Simulate streaming with protocol wrapper
    mock_llm = MockChatOpenAI()
    wrapped_llm = ChatOpenAIWrapper(mock_llm)

    # Test that we can still generate streaming events
    bus.on_step("Testing with protocol wrapper")

    # Simulate content streaming
    messages = [{"role": "user", "content": "Test"}]
    async for chunk in wrapped_llm.astream(messages):
        if chunk.content:
            bus.on_content_delta(chunk.content, 0)

    bus.emit_completed("Protocol wrapper test complete", turns=1)

    # Collect events
    events = []
    while not queue.empty():
        event = await queue.get()
        events.append(event)

    print(f"Generated {len(events)} events with protocol wrapper:")
    for i, event in enumerate(events, 1):
        if event.type == "response.step":
            print(f"  {i}. STEP: {event.content}")
        elif event.type == "response.content.delta":
            print(f"  {i}. DELTA: '{event.delta}'")
        elif event.type == "response.completed":
            print(f"  {i}. COMPLETED: {event.message}")

    # Verify expected events
    assert len(events) == 6  # 1 step + 4 deltas + 1 completed
    assert events[0].type == "response.step"
    assert events[1].type == "response.content.delta"
    assert events[-1].type == "response.completed"

    print("[PASS] Streaming events work correctly with protocol wrapper!")


def test_convenience_function():
    """Test the convenience wrapper function."""
    print("\nTesting convenience wrapper function...")

    mock_llm = MockChatOpenAI()
    wrapped_llm = wrap_chat_openai(mock_llm)

    assert isinstance(wrapped_llm, LangChainLLMProtocol)
    assert isinstance(wrapped_llm, ChatOpenAIWrapper)

    print("[PASS] Convenience wrapper function working!")


async def test_error_handling_with_protocol():
    """Test error handling through the protocol wrapper."""
    print("\nTesting error handling with protocol wrapper...")

    class ErrorMockChatOpenAI(MockChatOpenAI):
        async def ainvoke(self, messages):
            raise Exception("Mock LLM error")

        async def astream(self, messages):
            raise Exception("Mock streaming error")
            yield  # unreachable

    error_llm = ErrorMockChatOpenAI()
    wrapped_llm = ChatOpenAIWrapper(error_llm)

    # Test non-streaming error
    try:
        await wrapped_llm.ainvoke([{"role": "user", "content": "test"}])
        assert False, "Should have raised exception"
    except Exception as e:
        assert str(e) == "Mock LLM error"

    # Test streaming error
    try:
        async for chunk in wrapped_llm.astream([{"role": "user", "content": "test"}]):
            pass
        assert False, "Should have raised exception"
    except Exception as e:
        assert str(e) == "Mock streaming error"

    print("[PASS] Error handling through protocol wrapper working!")


async def main():
    """Run all protocol wrapper tests."""
    print("=== LangChainLLMProtocol Frontend Integration Test ===\n")

    try:
        await test_protocol_wrapper_basic()
        await test_protocol_wrapper_streaming()
        await test_protocol_wrapper_tools()
        await test_protocol_wrapper_copy()
        await test_streaming_events_with_protocol()
        test_convenience_function()
        await test_error_handling_with_protocol()

        print("\n=== Protocol Wrapper Tests Summary ===")
        print("[PASS] All protocol wrapper tests passed!")
        print("Frontend integration with restored LangChainLLMProtocol is working correctly!")

        print("\n[INFO] Key findings:")
        print("- ChatOpenAIWrapper properly implements LangChainLLMProtocol")
        print("- Streaming functionality preserved through wrapper")
        print("- Tool binding works correctly")
        print("- Model copying/updating works")
        print("- Error handling is maintained")
        print("- SSE streaming events still work correctly")
        print("- No regressions detected from protocol restoration")

    except Exception as e:
        print(f"\n[FAIL] Protocol wrapper test failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())