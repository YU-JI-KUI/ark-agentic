"""Tests for agent types."""

import pytest
from datetime import datetime

from ark_agentic.core.types import (
    AgentMessage,
    AgentToolResult,
    MessageRole,
    SessionEntry,
    SkillEntry,
    SkillMetadata,
    ToolCall,
    ToolResultType,
    TokenUsage,
)


class TestToolCall:
    """Tests for ToolCall."""

    def test_create(self) -> None:
        """Test ToolCall.create factory method."""
        tc = ToolCall.create("test_tool", {"arg1": "value1"})
        assert tc.name == "test_tool"
        assert tc.arguments == {"arg1": "value1"}
        assert tc.id.startswith("toolu_")
        assert len(tc.id) == 30  # "toolu_" + 24 hex chars


class TestAgentToolResult:
    """Tests for AgentToolResult."""

    def test_json_result(self) -> None:
        """Test JSON result creation."""
        result = AgentToolResult.json_result("tc1", {"key": "value"})
        assert result.tool_call_id == "tc1"
        assert result.result_type == ToolResultType.JSON
        assert result.content == {"key": "value"}
        assert not result.is_error

    def test_text_result(self) -> None:
        """Test text result creation."""
        result = AgentToolResult.text_result("tc1", "hello world")
        assert result.result_type == ToolResultType.TEXT
        assert result.content == "hello world"

    def test_error_result(self) -> None:
        """Test error result creation."""
        result = AgentToolResult.error_result("tc1", "Something went wrong")
        assert result.result_type == ToolResultType.ERROR
        assert result.is_error
        assert result.content == "Something went wrong"

    def test_image_result(self) -> None:
        """Test image result creation."""
        result = AgentToolResult.image_result("tc1", "base64data", "image/png")
        assert result.result_type == ToolResultType.IMAGE
        assert result.content == {"data": "base64data", "media_type": "image/png"}


class TestAgentMessage:
    """Tests for AgentMessage."""

    def test_system_message(self) -> None:
        """Test system message creation."""
        msg = AgentMessage.system("You are a helpful assistant.")
        assert msg.role == MessageRole.SYSTEM
        assert msg.content == "You are a helpful assistant."

    def test_user_message(self) -> None:
        """Test user message creation."""
        msg = AgentMessage.user("Hello!", {"source": "test"})
        assert msg.role == MessageRole.USER
        assert msg.content == "Hello!"
        assert msg.metadata == {"source": "test"}

    def test_assistant_message(self) -> None:
        """Test assistant message creation."""
        tc = ToolCall.create("test", {})
        msg = AgentMessage.assistant(
            content="Let me help.",
            tool_calls=[tc],
            thinking="Analyzing..."
        )
        assert msg.role == MessageRole.ASSISTANT
        assert msg.content == "Let me help."
        assert msg.tool_calls == [tc]
        assert msg.thinking == "Analyzing..."

    def test_tool_message(self) -> None:
        """Test tool message creation."""
        result = AgentToolResult.text_result("tc1", "done")
        msg = AgentMessage.tool([result])
        assert msg.role == MessageRole.TOOL
        assert msg.tool_results == [result]


class TestSessionEntry:
    """Tests for SessionEntry."""

    def test_create(self) -> None:
        """Test SessionEntry.create factory method."""
        session = SessionEntry.create(model="test-model", provider="test")
        assert session.model == "test-model"
        assert session.provider == "test"
        assert session.session_id
        assert session.messages == []

    def test_add_message(self) -> None:
        """Test adding messages to session."""
        session = SessionEntry.create()
        msg = AgentMessage.user("Hello")
        session.add_message(msg)
        assert len(session.messages) == 1
        assert session.messages[0] == msg

    def test_update_token_usage(self) -> None:
        """Test token usage update."""
        session = SessionEntry.create()
        session.update_token_usage(input_tokens=100, output_tokens=50)
        assert session.token_usage.input_tokens == 100
        assert session.token_usage.output_tokens == 50
        assert session.token_usage.total_tokens == 150

        # Cumulative
        session.update_token_usage(input_tokens=50, output_tokens=25)
        assert session.token_usage.input_tokens == 150
        assert session.token_usage.output_tokens == 75


class TestSkillMetadata:
    """Tests for SkillMetadata."""

    def test_default_values(self) -> None:
        """Test default values."""
        meta = SkillMetadata(name="test", description="A test skill")
        assert meta.name == "test"
        assert meta.description == "A test skill"
        assert meta.version == "1.0.0"
        assert meta.invocation_policy == "auto"
        assert meta.tags == []


class TestTokenUsage:
    """Tests for TokenUsage."""

    def test_total_tokens(self) -> None:
        """Test total tokens calculation."""
        usage = TokenUsage(input_tokens=100, output_tokens=50)
        assert usage.total_tokens == 150

    def test_cache_tokens(self) -> None:
        """Test cache token fields."""
        usage = TokenUsage(
            input_tokens=100,
            output_tokens=50,
            cache_read_tokens=20,
            cache_creation_tokens=10
        )
        assert usage.cache_read_tokens == 20
        assert usage.cache_creation_tokens == 10
