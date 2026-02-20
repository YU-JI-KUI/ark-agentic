"""Tests for session management."""

import pytest
import tempfile
from pathlib import Path

from ark_agentic.core.session import SessionManager
from ark_agentic.core.compaction import CompactionConfig
from ark_agentic.core.types import AgentMessage, MessageRole


class TestSessionManagerBasic:
    """Tests for SessionManager basic operations (no persistence)."""

    def test_create_session_sync(self) -> None:
        """Test synchronous session creation."""
        manager = SessionManager(enable_persistence=False)
        session = manager.create_session_sync(model="test-model", provider="test")
        assert session.session_id
        assert session.model == "test-model"
        assert session.provider == "test"

    def test_get_session(self) -> None:
        """Test session retrieval."""
        manager = SessionManager(enable_persistence=False)
        session = manager.create_session_sync()
        retrieved = manager.get_session(session.session_id)
        assert retrieved == session

    def test_get_session_not_found(self) -> None:
        """Test getting non-existent session."""
        manager = SessionManager(enable_persistence=False)
        assert manager.get_session("non-existent") is None

    def test_get_session_required(self) -> None:
        """Test required session retrieval."""
        manager = SessionManager(enable_persistence=False)
        session = manager.create_session_sync()
        retrieved = manager.get_session_required(session.session_id)
        assert retrieved == session

    def test_get_session_required_raises(self) -> None:
        """Test required session raises on not found."""
        manager = SessionManager(enable_persistence=False)
        with pytest.raises(KeyError):
            manager.get_session_required("non-existent")

    def test_delete_session_sync(self) -> None:
        """Test synchronous session deletion."""
        manager = SessionManager(enable_persistence=False)
        session = manager.create_session_sync()
        assert manager.delete_session_sync(session.session_id)
        assert manager.get_session(session.session_id) is None

    def test_delete_session_not_found(self) -> None:
        """Test deleting non-existent session."""
        manager = SessionManager(enable_persistence=False)
        assert not manager.delete_session_sync("non-existent")

    def test_list_sessions(self) -> None:
        """Test listing sessions."""
        manager = SessionManager(enable_persistence=False)
        manager.create_session_sync()
        manager.create_session_sync()
        sessions = manager.list_sessions()
        assert len(sessions) == 2


class TestSessionManagerMessages:
    """Tests for message management."""

    def test_add_message_sync(self) -> None:
        """Test synchronous message addition."""
        manager = SessionManager(enable_persistence=False)
        session = manager.create_session_sync()
        msg = AgentMessage.user("Hello")
        manager.add_message_sync(session.session_id, msg)
        messages = manager.get_messages(session.session_id)
        assert len(messages) == 1
        assert messages[0].content == "Hello"

    def test_get_messages_with_filter(self) -> None:
        """Test getting messages with filters."""
        manager = SessionManager(enable_persistence=False)
        session = manager.create_session_sync()

        manager.add_message_sync(session.session_id, AgentMessage.system("System"))
        manager.add_message_sync(session.session_id, AgentMessage.user("User 1"))
        manager.add_message_sync(session.session_id, AgentMessage.user("User 2"))

        # All messages
        all_msgs = manager.get_messages(session.session_id)
        assert len(all_msgs) == 3

        # Exclude system
        non_system = manager.get_messages(session.session_id, include_system=False)
        assert len(non_system) == 2

        # Limit
        limited = manager.get_messages(session.session_id, limit=1)
        assert len(limited) == 1
        assert limited[0].content == "User 2"

    def test_clear_messages(self) -> None:
        """Test clearing messages."""
        manager = SessionManager(enable_persistence=False)
        session = manager.create_session_sync()

        manager.add_message_sync(session.session_id, AgentMessage.system("System"))
        manager.add_message_sync(session.session_id, AgentMessage.user("User"))

        manager.clear_messages(session.session_id, keep_system=True)
        messages = manager.get_messages(session.session_id)
        assert len(messages) == 1
        assert messages[0].role == MessageRole.SYSTEM

    def test_clear_messages_all(self) -> None:
        """Test clearing all messages."""
        manager = SessionManager(enable_persistence=False)
        session = manager.create_session_sync()

        manager.add_message_sync(session.session_id, AgentMessage.system("System"))
        manager.add_message_sync(session.session_id, AgentMessage.user("User"))

        manager.clear_messages(session.session_id, keep_system=False)
        messages = manager.get_messages(session.session_id)
        assert len(messages) == 0


class TestSessionManagerTokens:
    """Tests for token management."""

    def test_update_token_usage(self) -> None:
        """Test token usage update."""
        manager = SessionManager(enable_persistence=False)
        session = manager.create_session_sync()

        manager.update_token_usage(session.session_id, prompt_tokens=100, completion_tokens=50)
        usage = manager.get_token_usage(session.session_id)
        assert usage.prompt_tokens == 100
        assert usage.completion_tokens == 50
        assert usage.total_tokens == 150

    def test_estimate_current_tokens(self) -> None:
        """Test current token estimation."""
        manager = SessionManager(enable_persistence=False)
        session = manager.create_session_sync()

        manager.add_message_sync(session.session_id, AgentMessage.user("Hello world"))
        tokens = manager.estimate_current_tokens(session.session_id)
        assert tokens > 0


class TestSessionManagerSkills:
    """Tests for skill management."""

    def test_set_active_skills(self) -> None:
        """Test setting active skills."""
        manager = SessionManager(enable_persistence=False)
        session = manager.create_session_sync()

        manager.set_active_skills(session.session_id, ["skill1", "skill2"])
        skills = manager.get_active_skills(session.session_id)
        assert skills == ["skill1", "skill2"]


class TestSessionManagerMetadata:
    """Tests for metadata management."""

    def test_update_metadata(self) -> None:
        """Test metadata update."""
        manager = SessionManager(enable_persistence=False)
        session = manager.create_session_sync()

        manager.update_metadata(session.session_id, {"key": "value"})
        meta = manager.get_metadata(session.session_id)
        assert meta["key"] == "value"

    def test_get_session_stats(self) -> None:
        """Test session statistics."""
        manager = SessionManager(enable_persistence=False)
        session = manager.create_session_sync()
        manager.add_message_sync(session.session_id, AgentMessage.user("Hello"))

        stats = manager.get_session_stats(session.session_id)
        assert stats["session_id"] == session.session_id
        assert stats["message_count"] == 1
        assert "estimated_tokens" in stats


class TestSessionManagerCompaction:
    """Tests for compaction."""

    def test_needs_compaction(self) -> None:
        """Test compaction check."""
        manager = SessionManager(
            compaction_config=CompactionConfig(
                context_window=100,
                output_reserve=10,
                system_reserve=10,
                trigger_threshold=0.5
            ),
            enable_persistence=False
        )
        session = manager.create_session_sync()

        # Small messages - no compaction
        manager.add_message_sync(session.session_id, AgentMessage.user("Hi"))
        assert not manager.needs_compaction(session.session_id)

    @pytest.mark.asyncio
    async def test_compact_session(self) -> None:
        """Test session compaction."""
        manager = SessionManager(
            compaction_config=CompactionConfig(preserve_recent=1),
            enable_persistence=False
        )
        session = manager.create_session_sync()

        # Add some messages
        for i in range(5):
            manager.add_message_sync(session.session_id, AgentMessage.user(f"Message {i}"))

        result = await manager.compact_session(session.session_id, force=True)
        assert result.original_count == 5


class TestSessionManagerPersistence:
    """Tests for session persistence."""

    @pytest.mark.asyncio
    async def test_create_session_with_persistence(self) -> None:
        """Test session creation with persistence."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SessionManager(
                sessions_dir=tmpdir,
                enable_persistence=True
            )
            session = await manager.create_session(model="test-model")
            assert session.session_id

            # Check file was created
            session_file = Path(tmpdir) / f"{session.session_id}.jsonl"
            assert session_file.exists()

    @pytest.mark.asyncio
    async def test_add_message_with_persistence(self) -> None:
        """Test message addition with persistence."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SessionManager(
                sessions_dir=tmpdir,
                enable_persistence=True
            )
            session = await manager.create_session()
            await manager.add_message(session.session_id, AgentMessage.user("Hello"))

            # Check message was persisted
            session_file = Path(tmpdir) / f"{session.session_id}.jsonl"
            content = session_file.read_text()
            assert "Hello" in content

    @pytest.mark.asyncio
    async def test_load_session(self) -> None:
        """Test loading session from persistence."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create and populate session
            manager1 = SessionManager(
                sessions_dir=tmpdir,
                enable_persistence=True
            )
            session = await manager1.create_session()
            await manager1.add_message(session.session_id, AgentMessage.user("Test message"))

            # Create new manager and load
            manager2 = SessionManager(
                sessions_dir=tmpdir,
                enable_persistence=True
            )
            loaded = await manager2.load_session(session.session_id)
            assert loaded is not None
            assert len(loaded.messages) == 1
            assert loaded.messages[0].content == "Test message"

    @pytest.mark.asyncio
    async def test_delete_session_with_persistence(self) -> None:
        """Test session deletion with persistence."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SessionManager(
                sessions_dir=tmpdir,
                enable_persistence=True
            )
            session = await manager.create_session()
            session_file = Path(tmpdir) / f"{session.session_id}.jsonl"

            assert session_file.exists()
            await manager.delete_session(session.session_id)
            assert not session_file.exists()
