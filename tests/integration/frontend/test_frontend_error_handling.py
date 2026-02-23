#!/usr/bin/env python3
"""
Test frontend error handling and UI functionality.
Tests error message display, tool call progress, and session management.
"""

import asyncio
import json
import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent / "src"))

from ark_agentic.core.stream.event_bus import StreamEventBus
from ark_agentic.core.stream.events import AgentStreamEvent


async def test_error_handling():
    """Test error event generation and handling."""
    print("Testing error handling...")

    queue = asyncio.Queue()
    bus = StreamEventBus(
        run_id="error-test-123",
        session_id="error-session-456",
        queue=queue
    )

    # Test different error scenarios
    bus.emit_failed("Authentication failed - please check your API key")
    bus.emit_failed("Network timeout - please try again")
    bus.emit_failed("Rate limit exceeded - please wait before retrying")

    # Collect error events
    events = []
    while not queue.empty():
        event = await queue.get()
        events.append(event)

    print(f"Generated {len(events)} error events:")
    for i, event in enumerate(events, 1):
        print(f"  {i}. {event.type}: {event.error_message}")

    # Validate error event structure
    assert len(events) == 3, f"Expected 3 error events, got {len(events)}"
    for event in events:
        assert event.type == "response.failed"
        assert event.error_message is not None
        assert len(event.error_message) > 0

    print("[PASS] Error handling test passed!")


async def test_tool_progress_indicators():
    """Test tool call progress and status indicators."""
    print("\nTesting tool call progress indicators...")

    queue = asyncio.Queue()
    bus = StreamEventBus(
        run_id="tool-test-123",
        session_id="tool-session-456",
        queue=queue
    )

    # Simulate tool execution flow
    bus.on_step("正在查询您的保单信息，请稍等…")
    bus.on_tool_call_start("policy_query", {"user_id": "U001", "policy_type": "life"})
    bus.on_step("正在验证身份信息…")
    bus.on_tool_call_result("policy_query", {"policy_id": "P123", "status": "active"})
    bus.on_step("信息收集完毕，正在为您总结…")

    # Collect events
    events = []
    while not queue.empty():
        event = await queue.get()
        events.append(event)

    print(f"Generated {len(events)} tool progress events:")
    for i, event in enumerate(events, 1):
        if event.type == "response.step":
            print(f"  {i}. STEP: {event.content}")
        elif event.type == "response.tool_call.start":
            print(f"  {i}. TOOL_START: {event.tool_name} with args {event.tool_args}")
        elif event.type == "response.tool_call.result":
            print(f"  {i}. TOOL_RESULT: {event.tool_name} -> {event.tool_result}")

    # Validate tool progress flow
    assert len(events) == 5, f"Expected 5 events, got {len(events)}"
    assert events[0].type == "response.step"
    assert events[1].type == "response.tool_call.start"
    assert events[2].type == "response.step"
    assert events[3].type == "response.tool_call.result"
    assert events[4].type == "response.step"

    print("[PASS] Tool progress indicators test passed!")


def test_sse_format_compatibility():
    """Test SSE format compatibility with frontend JavaScript."""
    print("\nTesting SSE format compatibility...")

    # Create sample events that match what the UI expects
    events = [
        AgentStreamEvent(
            type="response.created",
            seq=1,
            run_id="sse-test",
            session_id="sse-session",
            content="收到您的消息，正在处理中…"
        ),
        AgentStreamEvent(
            type="response.step",
            seq=2,
            run_id="sse-test",
            session_id="sse-session",
            content="正在查询保单信息…"
        ),
        AgentStreamEvent(
            type="response.content.delta",
            seq=3,
            run_id="sse-test",
            session_id="sse-session",
            delta="您的保单",
            output_index=0
        ),
        AgentStreamEvent(
            type="response.completed",
            seq=4,
            run_id="sse-test",
            session_id="sse-session",
            message="查询完成",
            turns=1,
            usage={"prompt_tokens": 50, "completion_tokens": 20}
        )
    ]

    print("SSE formatted events:")
    for event in events:
        # Format as SSE (Server-Sent Events)
        json_data = event.model_dump_json(exclude_none=True)
        sse_line = f"event: {event.type}\ndata: {json_data}\n"
        print(f"  {sse_line}")

        # Validate JSON can be parsed by frontend
        parsed = json.loads(json_data)
        assert "type" in parsed
        assert "seq" in parsed
        assert "run_id" in parsed
        assert "session_id" in parsed

    print("[PASS] SSE format compatibility test passed!")


def test_ui_event_types():
    """Test that all UI-expected event types are supported."""
    print("\nTesting UI event type coverage...")

    # Event types that the frontend JavaScript handles
    ui_expected_types = {
        "response.created",
        "response.step",
        "response.content.delta",
        "response.tool_call.start",
        "response.tool_call.result",
        "response.completed",
        "response.failed"
    }

    # Check against our event type definitions
    from ark_agentic.core.stream.events import EventType
    supported_types = set(EventType.__args__)

    print(f"UI expected types: {sorted(ui_expected_types)}")
    print(f"Supported types: {sorted(supported_types)}")

    missing = ui_expected_types - supported_types
    if missing:
        print(f"[FAIL] Missing event types: {missing}")
        return False
    else:
        print("[PASS] All UI event types are supported!")
        return True


async def main():
    """Run all frontend tests."""
    print("=== Frontend Error Handling & UI Tests ===\n")

    try:
        await test_error_handling()
        await test_tool_progress_indicators()
        test_sse_format_compatibility()
        ui_test_passed = test_ui_event_types()

        print("\n=== Frontend Tests Summary ===")
        if ui_test_passed:
            print("[PASS] All frontend tests passed!")
            print("Frontend is ready for LangChain integration!")
        else:
            print("[FAIL] Some frontend tests failed!")

    except Exception as e:
        print(f"\n[FAIL] Frontend test failed with error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())