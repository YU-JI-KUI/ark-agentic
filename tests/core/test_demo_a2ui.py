"""Tests for DemoA2UITool and A2UI component flow."""

import asyncio
import json

import pytest

from ark_agentic.core.tools.demo_a2ui import DemoA2UITool
from ark_agentic.core.types import ToolCall
from ark_agentic.core.stream.event_bus import StreamEventBus
from ark_agentic.core.stream.events import AgentStreamEvent
from ark_agentic.core.stream.output_formatter import EnterpriseAGUIFormatter


@pytest.mark.asyncio
async def test_demo_a2ui_tool_returns_ui_components() -> None:
    tool = DemoA2UITool()
    tc = ToolCall(id="tc_demo", name="demo_a2ui_card", arguments={"card_title": "测试"})
    result = await tool.execute(tc, context={"session_id": "s1"})

    assert not result.is_error
    assert "ui_components" in result.metadata
    assert len(result.metadata["ui_components"]) == 1

    component = result.metadata["ui_components"][0]
    assert component["sessionId"] == "s1"
    assert "answerDict" in component


@pytest.mark.asyncio
async def test_a2ui_component_flows_through_event_bus() -> None:
    """Simulate the Runner forwarding ui_components to the bus."""
    queue: asyncio.Queue[AgentStreamEvent] = asyncio.Queue()
    bus = StreamEventBus(run_id="r1", session_id="s1", queue=queue)

    tool = DemoA2UITool()
    tc = ToolCall(id="tc_demo", name="demo_a2ui_card", arguments={})
    result = await tool.execute(tc, context={})

    # Simulate what Runner does after tool execution
    bus.on_tool_call_start(tc.id, tc.name, tc.arguments)
    bus.on_tool_call_result(tc.id, tc.name, result.content)
    if result.metadata.get("ui_components"):
        for component in result.metadata["ui_components"]:
            bus.on_ui_component(component)

    events = []
    while not queue.empty():
        events.append(queue.get_nowait())

    types = [e.type for e in events]
    assert "tool_call_start" in types
    assert "tool_call_result" in types
    assert "text_message_content" in types

    a2ui_event = next(e for e in events if e.type == "text_message_content" and getattr(e, "content_kind", None) == "a2ui")
    assert "answerDict" in a2ui_event.custom_data


@pytest.mark.asyncio
async def test_demo_a2ui_tool_default_values() -> None:
    tool = DemoA2UITool()
    tc = ToolCall(id="tc_1", name="demo_a2ui_card", arguments={})
    result = await tool.execute(tc)

    assert result.content["title"] == "保单信息"
    assert result.content["status"] == "success"


@pytest.mark.asyncio
async def test_a2ui_component_encoded_as_enterprise_ui_data_json() -> None:
    """End-to-end: DemoA2UITool → StreamEventBus → EnterpriseAGUIFormatter produces ui_protocol=A2UI with JSON ui_data."""
    queue: asyncio.Queue[AgentStreamEvent] = asyncio.Queue()
    bus = StreamEventBus(run_id="r1", session_id="s1", queue=queue)
    formatter = EnterpriseAGUIFormatter(source_bu_type="shouxian", app_type="hcz")

    tool = DemoA2UITool()
    tc = ToolCall(id="tc_demo", name="demo_a2ui_card", arguments={})
    result = await tool.execute(tc, context={"session_id": "s1"})

    # Simulate Runner tool execution + ui_components forwarding
    bus.on_tool_call_start(tc.id, tc.name, tc.arguments)
    bus.on_tool_call_result(tc.id, tc.name, result.content)
    if result.metadata.get("ui_components"):
        for component in result.metadata["ui_components"]:
            bus.on_ui_component(component)

    # Drain queue, pick the text_message_content+a2ui event and format it
    events_list: list[AgentStreamEvent] = []
    while not queue.empty():
        events_list.append(queue.get_nowait())

    a2ui_event = next(e for e in events_list if e.type == "text_message_content" and getattr(e, "content_kind", None) == "a2ui")
    sse = formatter.format(a2ui_event)

    # Parse SSE and inspect AGUIEnvelope.data.ui_data
    event_type = ""
    data_json = ""
    for line in sse.split("\n"):
        if line.startswith("event: "):
            event_type = line[7:]
        elif line.startswith("data: "):
            data_json = line[6:]
    assert event_type == "text_message_content"

    envelope = json.loads(data_json)
    assert envelope["protocol"] == "AGUI"
    dp = envelope["data"]
    assert dp["ui_protocol"] == "A2UI"
    ui_data = dp["ui_data"]
    # ui_data 应该是一个 JSON A2UI 卡片结构，而不是字符串
    assert isinstance(ui_data, dict)
    assert "answerDict" in ui_data
    assert "result" in ui_data["answerDict"]
