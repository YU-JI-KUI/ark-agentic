#!/usr/bin/env python3
"""
Manual test for LangChain streaming integration.
Tests the current StreamEventBus and AgentStreamEvent system.
"""

import asyncio
import os
from pathlib import Path

# Add src to path for imports
import sys
sys.path.insert(0, str(Path(__file__).parent / "src"))

from ark_agentic.core.stream.event_bus import StreamEventBus
from ark_agentic.core.stream.events import AgentStreamEvent


async def test_stream_event_bus():
    """Test StreamEventBus functionality."""
    print("Testing StreamEventBus...")

    # Create event queue and bus
    queue = asyncio.Queue()
    bus = StreamEventBus(
        run_id="test-run-123",
        session_id="test-session-456",
        queue=queue
    )

    # Test basic events
    bus.on_step("Testing step event")
    bus.on_content_delta("Hello ", 0)
    bus.on_content_delta("world!", 0)
    bus.on_tool_call_start("test_tool", {"arg": "value"})
    bus.on_tool_call_result("test_tool", "Tool executed successfully")
    bus.emit_completed("Final response", turns=1, usage={"prompt_tokens": 10, "completion_tokens": 5})

    # Collect events
    events = []
    while not queue.empty():
        event = await queue.get()
        events.append(event)

    print(f"Generated {len(events)} events:")
    for i, event in enumerate(events, 1):
        print(f"  {i}. {event.type}: {event.content or event.delta or event.tool_name or 'completed'}")

    # Validate event structure
    assert len(events) == 6, f"Expected 6 events, got {len(events)}"
    assert events[0].type == "response.step"
    assert events[1].type == "response.content.delta"
    assert events[2].type == "response.content.delta"
    assert events[3].type == "response.tool_call.start"
    assert events[4].type == "response.tool_call.result"
    assert events[5].type == "response.completed"

    print("[PASS] StreamEventBus test passed!")


async def test_event_serialization():
    """Test AgentStreamEvent serialization for SSE."""
    print("\nTesting event serialization...")

    event = AgentStreamEvent(
        type="response.content.delta",
        seq=1,
        run_id="test-run",
        session_id="test-session",
        delta="Hello world",
        output_index=0
    )

    # Test JSON serialization
    json_data = event.model_dump_json(exclude_none=True)
    print(f"Serialized event: {json_data}")

    # Validate it can be parsed back
    import json
    parsed = json.loads(json_data)
    assert parsed["type"] == "response.content.delta"
    assert parsed["delta"] == "Hello world"
    assert "tool_name" not in parsed  # Should exclude None fields

    print("[PASS] Event serialization test passed!")


def test_ui_compatibility():
    """Test that events match expected UI format."""
    print("\nTesting UI compatibility...")

    # These are the event types the UI expects
    expected_types = {
        "response.created",
        "response.step",
        "response.content.delta",
        "response.tool_call.start",
        "response.tool_call.result",
        "response.completed",
        "response.failed"
    }

    # Check that our event types match
    from ark_agentic.core.stream.events import EventType
    actual_types = set(EventType.__args__)

    print(f"Expected types: {sorted(expected_types)}")
    print(f"Actual types: {sorted(actual_types)}")

    missing = expected_types - actual_types
    extra = actual_types - expected_types

    if missing:
        print(f"[FAIL] Missing event types: {missing}")
    if extra:
        print(f"[INFO] Extra event types: {extra}")

    if not missing:
        print("[PASS] UI compatibility test passed!")
    else:
        print("[FAIL] UI compatibility test failed!")


async def main():
    """Run all tests."""
    print("=== LangChain Streaming Integration Test ===\n")

    try:
        await test_stream_event_bus()
        await test_event_serialization()
        test_ui_compatibility()

        print("\n=== All Tests Completed ===")
        print("[PASS] LangChain streaming integration appears to be working correctly!")

    except Exception as e:
        print(f"\n[FAIL] Test failed with error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())