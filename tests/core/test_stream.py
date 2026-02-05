"""Tests for stream assembler."""

import pytest
from ark_agentic.core.stream.assembler import (
    StreamAssembler,
    StreamEvent,
    StreamEventType,
    StreamState,
    parse_anthropic_sse,
    parse_openai_sse,
)


class TestStreamState:
    """Tests for StreamState."""

    def test_default_values(self) -> None:
        """Test default state values."""
        state = StreamState()
        assert state.content == ""
        assert state.thinking == ""
        assert state.tool_calls == []
        assert state.current_tool_index == -1
        assert not state.is_complete
        assert state.error is None


class TestStreamAssembler:
    """Tests for StreamAssembler."""

    def test_content_accumulation(self) -> None:
        """Test content delta accumulation."""
        assembler = StreamAssembler()

        assembler.process_event(StreamEvent(
            type=StreamEventType.CONTENT_DELTA,
            data="Hello "
        ))
        assembler.process_event(StreamEvent(
            type=StreamEventType.CONTENT_DELTA,
            data="world!"
        ))

        assert assembler.state.content == "Hello world!"

    def test_thinking_accumulation(self) -> None:
        """Test thinking delta accumulation."""
        assembler = StreamAssembler()

        assembler.process_event(StreamEvent(
            type=StreamEventType.THINKING_DELTA,
            data="Let me "
        ))
        assembler.process_event(StreamEvent(
            type=StreamEventType.THINKING_DELTA,
            data="think..."
        ))

        assert assembler.state.thinking == "Let me think..."

    def test_tool_call_accumulation(self) -> None:
        """Test tool call accumulation."""
        assembler = StreamAssembler()

        # Tool start
        assembler.process_event(StreamEvent(
            type=StreamEventType.TOOL_USE_START,
            data={"id": "tc1", "name": "test_tool"}
        ))

        # Tool arguments
        assembler.process_event(StreamEvent(
            type=StreamEventType.TOOL_USE_DELTA,
            data='{"arg":'
        ))
        assembler.process_event(StreamEvent(
            type=StreamEventType.TOOL_USE_DELTA,
            data='"value"}'
        ))

        # Tool end
        assembler.process_event(StreamEvent(
            type=StreamEventType.TOOL_USE_END
        ))

        assert len(assembler.state.tool_calls) == 1
        assert assembler.state.tool_calls[0]["name"] == "test_tool"
        assert assembler.state.tool_calls[0]["input"] == '{"arg":"value"}'

    def test_build_message(self) -> None:
        """Test building final message."""
        assembler = StreamAssembler()

        assembler.process_event(StreamEvent(
            type=StreamEventType.CONTENT_DELTA,
            data="Hello"
        ))
        assembler.process_event(StreamEvent(
            type=StreamEventType.MESSAGE_END,
            data={"usage": {"input_tokens": 10, "output_tokens": 5}}
        ))

        message = assembler.build_message()
        assert message.content == "Hello"
        assert message.role.value == "assistant"

    def test_build_message_with_tools(self) -> None:
        """Test building message with tool calls."""
        assembler = StreamAssembler()

        assembler.process_event(StreamEvent(
            type=StreamEventType.TOOL_USE_START,
            data={"id": "tc1", "name": "tool1"}
        ))
        assembler.process_event(StreamEvent(
            type=StreamEventType.TOOL_USE_DELTA,
            data='{"x": 1}'
        ))
        assembler.process_event(StreamEvent(
            type=StreamEventType.TOOL_USE_END
        ))

        message = assembler.build_message()
        assert message.tool_calls is not None
        assert len(message.tool_calls) == 1
        assert message.tool_calls[0].name == "tool1"
        assert message.tool_calls[0].arguments == {"x": 1}

    def test_error_handling(self) -> None:
        """Test error event handling."""
        assembler = StreamAssembler()

        assembler.process_event(StreamEvent(
            type=StreamEventType.ERROR,
            data="Something went wrong"
        ))

        assert assembler.state.error == "Something went wrong"

    def test_callbacks(self) -> None:
        """Test callbacks are called."""
        content_chunks = []
        thinking_chunks = []

        assembler = StreamAssembler(
            on_content=lambda c: content_chunks.append(c),
            on_thinking=lambda t: thinking_chunks.append(t),
        )

        assembler.process_event(StreamEvent(
            type=StreamEventType.CONTENT_DELTA,
            data="Hello"
        ))
        assembler.process_event(StreamEvent(
            type=StreamEventType.THINKING_DELTA,
            data="Thinking..."
        ))

        assert content_chunks == ["Hello"]
        assert thinking_chunks == ["Thinking..."]

    def test_reset(self) -> None:
        """Test state reset."""
        assembler = StreamAssembler()

        assembler.process_event(StreamEvent(
            type=StreamEventType.CONTENT_DELTA,
            data="Hello"
        ))

        assembler.reset()
        assert assembler.state.content == ""


class TestParseAnthropicSSE:
    """Tests for Anthropic SSE parsing."""

    def test_message_start(self) -> None:
        """Test message_start event."""
        event = parse_anthropic_sse({
            "type": "message_start",
            "message": {"id": "msg1"}
        })
        assert event is not None
        assert event.type == StreamEventType.MESSAGE_START

    def test_content_block_start_text(self) -> None:
        """Test content_block_start for text."""
        event = parse_anthropic_sse({
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "text"}
        })
        assert event is not None
        assert event.type == StreamEventType.CONTENT_START

    def test_content_block_start_tool(self) -> None:
        """Test content_block_start for tool_use."""
        event = parse_anthropic_sse({
            "type": "content_block_start",
            "index": 0,
            "content_block": {
                "type": "tool_use",
                "id": "tc1",
                "name": "test_tool"
            }
        })
        assert event is not None
        assert event.type == StreamEventType.TOOL_USE_START
        assert event.data["id"] == "tc1"
        assert event.data["name"] == "test_tool"

    def test_content_block_delta_text(self) -> None:
        """Test content_block_delta for text."""
        event = parse_anthropic_sse({
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": "Hello"}
        })
        assert event is not None
        assert event.type == StreamEventType.CONTENT_DELTA
        assert event.data == "Hello"

    def test_content_block_delta_tool(self) -> None:
        """Test content_block_delta for tool input."""
        event = parse_anthropic_sse({
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "input_json_delta", "partial_json": '{"x":'}
        })
        assert event is not None
        assert event.type == StreamEventType.TOOL_USE_DELTA
        assert event.data == '{"x":'

    def test_message_stop(self) -> None:
        """Test message_stop event."""
        event = parse_anthropic_sse({"type": "message_stop"})
        assert event is not None
        assert event.type == StreamEventType.MESSAGE_END

    def test_error(self) -> None:
        """Test error event."""
        event = parse_anthropic_sse({
            "type": "error",
            "error": {"message": "Error occurred"}
        })
        assert event is not None
        assert event.type == StreamEventType.ERROR


class TestParseOpenAISSE:
    """Tests for OpenAI SSE parsing."""

    def test_content_delta(self) -> None:
        """Test content delta."""
        event = parse_openai_sse({
            "choices": [{
                "delta": {"content": "Hello"},
                "finish_reason": None
            }]
        })
        assert event is not None
        assert event.type == StreamEventType.CONTENT_DELTA
        assert event.data == "Hello"

    def test_tool_call_start(self) -> None:
        """Test tool call start."""
        event = parse_openai_sse({
            "choices": [{
                "delta": {
                    "tool_calls": [{
                        "index": 0,
                        "id": "tc1",
                        "function": {"name": "test_tool"}
                    }]
                },
                "finish_reason": None
            }]
        })
        assert event is not None
        assert event.type == StreamEventType.TOOL_USE_START
        assert event.data["name"] == "test_tool"

    def test_tool_call_arguments(self) -> None:
        """Test tool call arguments delta."""
        event = parse_openai_sse({
            "choices": [{
                "delta": {
                    "tool_calls": [{
                        "index": 0,
                        "function": {"arguments": '{"x":1}'}
                    }]
                },
                "finish_reason": None
            }]
        })
        assert event is not None
        assert event.type == StreamEventType.TOOL_USE_DELTA
        assert event.data == '{"x":1}'

    def test_finish_reason(self) -> None:
        """Test finish_reason."""
        event = parse_openai_sse({
            "choices": [{
                "delta": {},
                "finish_reason": "stop"
            }]
        })
        assert event is not None
        assert event.type == StreamEventType.MESSAGE_END
        assert event.data["finish_reason"] == "stop"

    def test_empty_choices(self) -> None:
        """Test empty choices."""
        event = parse_openai_sse({"choices": []})
        assert event is None
