"""Tests for session persistence."""

import json
import pytest
import tempfile
from pathlib import Path

from ark_agentic.core.session.format import (
    SessionHeader,
    deserialize_message,
    deserialize_tool_call,
    deserialize_tool_result,
    serialize_message,
    serialize_tool_call,
    serialize_tool_result,
)
from ark_agentic.core.storage.entries import SessionStoreEntry
from ark_agentic.core.storage.repository.file._lock import FileLock
from ark_agentic.core.types import (
    AgentMessage,
    AgentToolResult,
    ToolCall,
    ToolResultType,
)


class TestSerialization:
    """Tests for message serialization."""

    def test_serialize_tool_call(self) -> None:
        """Test tool call serialization."""
        tc = ToolCall(id="tc1", name="test_tool", arguments={"arg": "value"})
        serialized = serialize_tool_call(tc)
        assert serialized["id"] == "tc1"
        assert serialized["type"] == "function"
        assert serialized["function"]["name"] == "test_tool"
        assert json.loads(serialized["function"]["arguments"]) == {"arg": "value"}

    def test_deserialize_tool_call(self) -> None:
        """Test tool call deserialization."""
        data = {
            "id": "tc1",
            "function": {
                "name": "test_tool",
                "arguments": '{"arg": "value"}'
            }
        }
        tc = deserialize_tool_call(data)
        assert tc.id == "tc1"
        assert tc.name == "test_tool"
        assert tc.arguments == {"arg": "value"}

    def test_serialize_tool_result(self) -> None:
        """Test tool result serialization."""
        tr = AgentToolResult.json_result("tc1", {"key": "value"})
        serialized = serialize_tool_result(tr)
        assert serialized["tool_call_id"] == "tc1"
        assert json.loads(serialized["content"]) == {"key": "value"}
        assert not serialized["is_error"]
        assert serialized["result_type"] == "json"

    def test_serialize_tool_result_preserves_a2ui_type(self) -> None:
        """A2UI result_type must survive serialization."""
        tr = AgentToolResult.a2ui_result("tc_a2ui", {"event": "beginRendering", "surfaceId": "s1"})
        serialized = serialize_tool_result(tr)
        assert serialized["result_type"] == "a2ui"

    def test_deserialize_tool_result(self) -> None:
        """Test tool result deserialization."""
        data = {
            "tool_call_id": "tc1",
            "content": '{"key": "value"}',
            "is_error": False
        }
        tr = deserialize_tool_result(data)
        assert tr.tool_call_id == "tc1"
        assert tr.content == {"key": "value"}
        assert tr.result_type == ToolResultType.JSON

    def test_deserialize_tool_result_restores_a2ui_type(self) -> None:
        """result_type=a2ui must be restored when present in serialized data."""
        data = {
            "tool_call_id": "tc_a2ui",
            "result_type": "a2ui",
            "content": '{"event": "beginRendering", "surfaceId": "s1"}',
            "is_error": False,
        }
        tr = deserialize_tool_result(data)
        assert tr.result_type == ToolResultType.A2UI
        assert tr.content == {"event": "beginRendering", "surfaceId": "s1"}

    def test_deserialize_tool_result_backward_compat_no_result_type(self) -> None:
        """Old JSONL data without result_type field must still deserialize correctly."""
        data = {
            "tool_call_id": "tc_old",
            "content": '{"key": "value"}',
            "is_error": False,
        }
        tr = deserialize_tool_result(data)
        assert tr.result_type == ToolResultType.JSON
        assert tr.content == {"key": "value"}

    def test_a2ui_result_roundtrip(self) -> None:
        """A2UI result must survive serialize→deserialize without type loss."""
        original = AgentToolResult.a2ui_result(
            "tc_rt", {"event": "beginRendering", "surfaceId": "s1", "components": []}
        )
        serialized = serialize_tool_result(original)
        restored = deserialize_tool_result(serialized)
        assert restored.result_type == ToolResultType.A2UI
        assert restored.content == original.content

    def test_serialize_message_user(self) -> None:
        """Test user message serialization."""
        msg = AgentMessage.user("Hello world")
        serialized = serialize_message(msg)
        assert serialized["role"] == "user"
        assert serialized["content"][0]["type"] == "text"
        assert serialized["content"][0]["text"] == "Hello world"

    def test_serialize_message_assistant_with_tools(self) -> None:
        """Test assistant message with tool calls."""
        tc = ToolCall(id="tc1", name="test", arguments={"x": 1})
        msg = AgentMessage.assistant(content="Let me help", tool_calls=[tc])
        serialized = serialize_message(msg)
        assert serialized["role"] == "assistant"
        assert len(serialized["tool_calls"]) == 1

    def test_deserialize_message(self) -> None:
        """Test message deserialization."""
        data = {
            "role": "user",
            "content": [{"type": "text", "text": "Hello"}]
        }
        msg = deserialize_message(data)
        assert msg.role.value == "user"
        assert msg.content == "Hello"


class TestSessionHeader:
    """Tests for SessionHeader."""

    def test_to_dict(self) -> None:
        """Test header to dict."""
        header = SessionHeader(
            id="session-123",
            timestamp="2024-01-01T00:00:00Z",
            cwd="/test"
        )
        d = header.to_dict()
        assert d["type"] == "session"
        assert d["id"] == "session-123"

    def test_from_dict(self) -> None:
        """Test header from dict."""
        data = {
            "type": "session",
            "version": 1,
            "id": "session-123",
            "timestamp": "2024-01-01T00:00:00Z",
            "cwd": "/test"
        }
        header = SessionHeader.from_dict(data)
        assert header.id == "session-123"
        assert header.timestamp == "2024-01-01T00:00:00Z"


class TestFileLock:
    """Tests for FileLock."""

    @pytest.mark.asyncio
    async def test_lock_acquire_release(self) -> None:
        """Test lock acquisition and release."""
        with tempfile.TemporaryDirectory() as tmpdir:
            lock_path = Path(tmpdir) / "test.lock"
            lock = FileLock(lock_path)

            acquired = await lock.acquire()
            assert acquired
            assert lock_path.exists()

            lock.release()
            assert not lock_path.exists()

    @pytest.mark.asyncio
    async def test_lock_context_manager(self) -> None:
        """Test lock as context manager."""
        with tempfile.TemporaryDirectory() as tmpdir:
            lock_path = Path(tmpdir) / "test.lock"

            async with FileLock(lock_path):
                assert lock_path.exists()

            assert not lock_path.exists()


class TestSessionStoreEntry:
    """Tests for SessionStoreEntry."""

    def test_to_dict(self) -> None:
        """Test entry to dict."""
        entry = SessionStoreEntry(
            session_id="session-123",
            updated_at=1234567890,
            model="test-model",
            provider="test"
        )
        d = entry.to_dict()
        assert d["sessionId"] == "session-123"
        assert d["model"] == "test-model"

    def test_from_dict(self) -> None:
        """Test entry from dict."""
        data = {
            "sessionId": "session-123",
            "updatedAt": 1234567890,
            "model": "test-model",
            "provider": "test"
        }
        entry = SessionStoreEntry.from_dict(data)
        assert entry.session_id == "session-123"
        assert entry.model == "test-model"

    def test_dto_lives_in_storage_entries_module(self) -> None:
        """SessionStoreEntry is the backend-neutral DTO under
        ``core.storage.entries`` — sole canonical home."""
        from ark_agentic.core.storage import entries as storage_entries

        assert SessionStoreEntry is storage_entries.SessionStoreEntry

    def test_dto_round_trip_does_not_carry_file_paths(self) -> None:
        """Backend-neutral: the DTO no longer exposes ``session_ref`` /
        ``sessionFile`` keys. ``to_dict`` -> ``from_dict`` round-trips
        without any file-system reference."""
        entry = SessionStoreEntry(
            session_id="s1", updated_at=1, model="m", provider="p",
            state={"k": "v"},
        )
        as_dict = entry.to_dict()
        assert "sessionFile" not in as_dict
        assert "session_ref" not in as_dict

        loaded = SessionStoreEntry.from_dict(as_dict)
        assert loaded == entry
