"""Tests for session persistence."""

import json
import pytest
import tempfile
from pathlib import Path

from ark_agentic.core.persistence import (
    FileLock,
    MessageEntry,
    RawJsonlValidationError,
    SessionHeader,
    SessionStore,
    SessionStoreEntry,
    TranscriptManager,
    deserialize_message,
    deserialize_tool_call,
    deserialize_tool_result,
    serialize_message,
    serialize_tool_call,
    serialize_tool_result,
)
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


class TestTranscriptManager:
    """Tests for TranscriptManager."""

    @pytest.mark.asyncio
    async def test_ensure_header(self) -> None:
        """Test header creation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = TranscriptManager(tmpdir)
            await manager.ensure_header("session-123")

            session_file = Path(tmpdir) / "session-123.jsonl"
            assert session_file.exists()

            content = session_file.read_text()
            first_line = json.loads(content.strip().split("\n")[0])
            assert first_line["type"] == "session"
            assert first_line["id"] == "session-123"

    @pytest.mark.asyncio
    async def test_append_message(self) -> None:
        """Test message appending."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = TranscriptManager(tmpdir)
            await manager.append_message("session-123", AgentMessage.user("Hello"))

            session_file = Path(tmpdir) / "session-123.jsonl"
            lines = session_file.read_text().strip().split("\n")
            assert len(lines) == 2  # header + message

            msg_data = json.loads(lines[1])
            assert msg_data["type"] == "message"
            assert msg_data["message"]["role"] == "user"

    @pytest.mark.asyncio
    async def test_append_messages_batch(self) -> None:
        """Test batch message appending."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = TranscriptManager(tmpdir)
            messages = [
                AgentMessage.user("Message 1"),
                AgentMessage.user("Message 2"),
                AgentMessage.user("Message 3"),
            ]
            await manager.append_messages("session-123", messages)

            session_file = Path(tmpdir) / "session-123.jsonl"
            lines = session_file.read_text().strip().split("\n")
            assert len(lines) == 4  # header + 3 messages

    def test_load_messages(self) -> None:
        """Test message loading."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = TranscriptManager(tmpdir)
            session_file = Path(tmpdir) / "session-123.jsonl"

            # Write test data
            header = {"type": "session", "version": 1, "id": "session-123"}
            msg1 = {"type": "message", "message": {"role": "user", "content": "Hello"}}
            msg2 = {"type": "message", "message": {"role": "assistant", "content": "Hi"}}

            with open(session_file, "w") as f:
                f.write(json.dumps(header) + "\n")
                f.write(json.dumps(msg1) + "\n")
                f.write(json.dumps(msg2) + "\n")

            messages = manager.load_messages("session-123")
            assert len(messages) == 2
            assert messages[0].content == "Hello"
            assert messages[1].content == "Hi"

    def test_load_header(self) -> None:
        """Test header loading."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = TranscriptManager(tmpdir)
            session_file = Path(tmpdir) / "session-123.jsonl"

            header_data = {
                "type": "session",
                "version": 1,
                "id": "session-123",
                "timestamp": "2024-01-01T00:00:00Z"
            }
            with open(session_file, "w") as f:
                f.write(json.dumps(header_data) + "\n")

            header = manager.load_header("session-123")
            assert header is not None
            assert header.id == "session-123"

    def test_get_recent_content(self) -> None:
        """Test getting recent content."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = TranscriptManager(tmpdir)
            session_file = Path(tmpdir) / "session-123.jsonl"

            # Write test data
            header = {"type": "session", "version": 1, "id": "session-123"}
            messages = [
                {"type": "message", "message": {"role": "user", "content": "Question 1"}},
                {"type": "message", "message": {"role": "assistant", "content": "Answer 1"}},
                {"type": "message", "message": {"role": "user", "content": "Question 2"}},
            ]

            with open(session_file, "w") as f:
                f.write(json.dumps(header) + "\n")
                for msg in messages:
                    f.write(json.dumps(msg) + "\n")

            content = manager.get_recent_content("session-123", message_count=10)
            assert content is not None
            assert "Question 1" in content
            assert "Answer 1" in content

    def test_list_sessions(self) -> None:
        """Test listing sessions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = TranscriptManager(tmpdir)

            # Create some session files
            for i in range(3):
                (Path(tmpdir) / f"session-{i}.jsonl").touch()

            sessions = manager.list_sessions()
            assert len(sessions) == 3

    def test_delete_session(self) -> None:
        """Test session deletion."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = TranscriptManager(tmpdir)
            session_file = Path(tmpdir) / "session-123.jsonl"
            session_file.touch()

            assert manager.delete_session("session-123")
            assert not session_file.exists()

    def test_session_exists(self) -> None:
        """Test session existence check."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = TranscriptManager(tmpdir)

            assert not manager.session_exists("session-123")

            (Path(tmpdir) / "session-123.jsonl").touch()
            assert manager.session_exists("session-123")

    def test_read_raw(self) -> None:
        """Test read_raw returns file content or None."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = TranscriptManager(tmpdir)
            assert manager.read_raw("s1") is None
            (Path(tmpdir) / "s1.jsonl").write_text('{"type":"session","id":"s1"}\n', encoding="utf-8")
            assert manager.read_raw("s1") == '{"type":"session","id":"s1"}\n'

    @pytest.mark.asyncio
    async def test_write_raw_valid(self) -> None:
        """Test write_raw with valid JSONL."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = TranscriptManager(tmpdir)
            content = '{"type":"session","id":"s1","timestamp":"","cwd":""}\n'
            await manager.write_raw("s1", content)
            assert (Path(tmpdir) / "s1.jsonl").read_text(encoding="utf-8") == content

    @pytest.mark.asyncio
    async def test_write_raw_validation_error(self) -> None:
        """Test write_raw raises RawJsonlValidationError for invalid content."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = TranscriptManager(tmpdir)
            with pytest.raises(RawJsonlValidationError) as exc_info:
                await manager.write_raw("s1", '{"type":"message"}\n')
            assert exc_info.value.line_number == 1
            with pytest.raises(RawJsonlValidationError):
                await manager.write_raw("s1", '{"type":"session","id":"other"}\n')


class TestSessionStore:
    """Tests for SessionStore."""

    def test_load_empty(self) -> None:
        """Test loading empty store."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store_path = Path(tmpdir) / "sessions.json"
            store = SessionStore(store_path)
            data = store.load()
            assert data == {}

    @pytest.mark.asyncio
    async def test_save_and_load(self) -> None:
        """Test saving and loading."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store_path = Path(tmpdir) / "sessions.json"
            store = SessionStore(store_path)

            entry = SessionStoreEntry(
                session_id="session-123",
                updated_at=1234567890,
                model="test-model"
            )
            await store.save({"session-123": entry})

            loaded = store.load(skip_cache=True)
            assert "session-123" in loaded
            assert loaded["session-123"].model == "test-model"

    @pytest.mark.asyncio
    async def test_update_entry(self) -> None:
        """Test updating single entry."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store_path = Path(tmpdir) / "sessions.json"
            store = SessionStore(store_path)

            entry = SessionStoreEntry(
                session_id="session-123",
                updated_at=1234567890,
                model="test-model"
            )
            await store.update("session-123", entry)

            loaded = store.get("session-123")
            assert loaded is not None
            assert loaded.session_id == "session-123"

    @pytest.mark.asyncio
    async def test_delete_entry(self) -> None:
        """Test deleting entry."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store_path = Path(tmpdir) / "sessions.json"
            store = SessionStore(store_path)

            entry = SessionStoreEntry(
                session_id="session-123",
                updated_at=1234567890
            )
            await store.update("session-123", entry)
            assert await store.delete("session-123")
            assert store.get("session-123") is None

    def test_list_keys(self) -> None:
        """Test listing keys."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store_path = Path(tmpdir) / "sessions.json"

            # Write test data
            data = {
                "session-1": {"sessionId": "session-1", "updatedAt": 0},
                "session-2": {"sessionId": "session-2", "updatedAt": 0},
            }
            with open(store_path, "w") as f:
                json.dump(data, f)

            store = SessionStore(store_path)
            keys = store.list_keys()
            assert set(keys) == {"session-1", "session-2"}


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
