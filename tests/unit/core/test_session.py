"""Tests for session management."""

import time

import pytest
from pathlib import Path

from ark_agentic.core.session.manager import SessionManager
from ark_agentic.core.session.compaction import CompactionConfig
from ark_agentic.core.storage.entries import SessionStoreEntry
from ark_agentic.core.types import AgentMessage, MessageRole, SessionEntry


class TestSessionManagerBasic:
    """Tests for SessionManager basic operations."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_sessions_dir: Path) -> None:
        self.sessions_dir = tmp_sessions_dir

    def test_create_session_sync(self) -> None:
        manager = SessionManager(self.sessions_dir)
        session = manager.create_session_sync(model="test-model", provider="test")
        assert session.session_id
        assert session.model == "test-model"
        assert session.provider == "test"

    def test_get_session(self) -> None:
        manager = SessionManager(self.sessions_dir)
        session = manager.create_session_sync()
        assert manager.get_session(session.session_id) == session

    def test_get_session_not_found(self) -> None:
        manager = SessionManager(self.sessions_dir)
        assert manager.get_session("non-existent") is None

    def test_get_session_required(self) -> None:
        manager = SessionManager(self.sessions_dir)
        session = manager.create_session_sync()
        assert manager.get_session_required(session.session_id) == session

    def test_get_session_required_raises(self) -> None:
        manager = SessionManager(self.sessions_dir)
        with pytest.raises(KeyError):
            manager.get_session_required("non-existent")

    def test_delete_session_sync(self) -> None:
        manager = SessionManager(self.sessions_dir)
        session = manager.create_session_sync()
        assert manager.delete_session_sync(session.session_id)
        assert manager.get_session(session.session_id) is None

    def test_delete_session_not_found(self) -> None:
        manager = SessionManager(self.sessions_dir)
        assert not manager.delete_session_sync("non-existent")

    def test_list_sessions(self) -> None:
        manager = SessionManager(self.sessions_dir)
        manager.create_session_sync()
        manager.create_session_sync()
        assert len(manager.list_sessions()) == 2

    def test_create_session_sync_with_custom_id(self) -> None:
        manager = SessionManager(self.sessions_dir)
        session = manager.create_session_sync(session_id="custom-id-001")
        assert session.session_id == "custom-id-001"
        assert manager.get_session("custom-id-001") is session

    def test_create_session_sync_with_user_id(self) -> None:
        manager = SessionManager(self.sessions_dir)
        session = manager.create_session_sync(user_id="user_42")
        assert session.user_id == "user_42"

    def test_create_session_sync_with_both_custom_id_and_user_id(self) -> None:
        manager = SessionManager(self.sessions_dir)
        session = manager.create_session_sync(
            session_id="parent:sub:abc", user_id="user_99",
            state={"user:id": "user_99"},
        )
        assert session.session_id == "parent:sub:abc"
        assert session.user_id == "user_99"
        assert session.state["user:id"] == "user_99"
        assert manager.get_session("parent:sub:abc") is session


class TestSessionManagerMessages:
    """Tests for message management."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_sessions_dir: Path) -> None:
        self.sessions_dir = tmp_sessions_dir

    def test_add_message_sync(self) -> None:
        manager = SessionManager(self.sessions_dir)
        session = manager.create_session_sync()
        manager.add_message_sync(session.session_id, AgentMessage.user("Hello"))
        messages = manager.get_messages(session.session_id)
        assert len(messages) == 1
        assert messages[0].content == "Hello"

    def test_get_messages_with_filter(self) -> None:
        manager = SessionManager(self.sessions_dir)
        session = manager.create_session_sync()

        manager.add_message_sync(session.session_id, AgentMessage.system("System"))
        manager.add_message_sync(session.session_id, AgentMessage.user("User 1"))
        manager.add_message_sync(session.session_id, AgentMessage.user("User 2"))

        assert len(manager.get_messages(session.session_id)) == 3
        assert len(manager.get_messages(session.session_id, include_system=False)) == 2
        limited = manager.get_messages(session.session_id, limit=1)
        assert len(limited) == 1
        assert limited[0].content == "User 2"

    def test_clear_messages(self) -> None:
        manager = SessionManager(self.sessions_dir)
        session = manager.create_session_sync()
        manager.add_message_sync(session.session_id, AgentMessage.system("System"))
        manager.add_message_sync(session.session_id, AgentMessage.user("User"))
        manager.clear_messages(session.session_id, keep_system=True)
        messages = manager.get_messages(session.session_id)
        assert len(messages) == 1
        assert messages[0].role == MessageRole.SYSTEM

    def test_clear_messages_all(self) -> None:
        manager = SessionManager(self.sessions_dir)
        session = manager.create_session_sync()
        manager.add_message_sync(session.session_id, AgentMessage.system("System"))
        manager.add_message_sync(session.session_id, AgentMessage.user("User"))
        manager.clear_messages(session.session_id, keep_system=False)
        assert len(manager.get_messages(session.session_id)) == 0


class TestSessionManagerTokens:
    """Tests for token management."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_sessions_dir: Path) -> None:
        self.sessions_dir = tmp_sessions_dir

    def test_update_token_usage(self) -> None:
        manager = SessionManager(self.sessions_dir)
        session = manager.create_session_sync()
        manager.update_token_usage(session.session_id, prompt_tokens=100, completion_tokens=50)
        usage = manager.get_token_usage(session.session_id)
        assert usage.prompt_tokens == 100
        assert usage.completion_tokens == 50
        assert usage.total_tokens == 150

    def test_estimate_current_tokens(self) -> None:
        manager = SessionManager(self.sessions_dir)
        session = manager.create_session_sync()
        manager.add_message_sync(session.session_id, AgentMessage.user("Hello world"))
        assert manager.estimate_current_tokens(session.session_id) > 0


class TestSessionEntryActiveSkillIds:
    """Tests for SessionEntry active_skill_ids SSOT field."""

    def test_session_entry_active_skill_ids_roundtrip(self) -> None:
        session = SessionEntry.create()
        session.active_skill_ids = ["a", "b"]
        # newest wins → [-1]
        assert session.current_active_skill_id == "b"

        original_updated_at = session.updated_at
        time.sleep(0.001)
        session.set_active_skill_ids(["c"])
        assert session.active_skill_ids == ["c"]
        assert session.current_active_skill_id == "c"
        assert session.updated_at > original_updated_at

    def test_session_entry_current_active_skill_id_empty(self) -> None:
        session = SessionEntry.create()
        assert session.active_skill_ids == []
        assert session.current_active_skill_id is None

    def test_session_store_entry_persists_active_skill_ids(self) -> None:
        entry = SessionStoreEntry(
            session_id="s1",
            updated_at=0,
            active_skill_ids=["a", "b"],
        )
        d = entry.to_dict()
        assert d["activeSkillIds"] == ["a", "b"]
        # legacy key not emitted
        assert "activeSkills" not in d
        # roundtrip
        restored = SessionStoreEntry.from_dict(d)
        assert restored.active_skill_ids == ["a", "b"]


class TestSessionManagerSkills:
    """Tests for skill management."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_sessions_dir: Path) -> None:
        self.sessions_dir = tmp_sessions_dir

    def test_set_active_skill_ids(self) -> None:
        manager = SessionManager(self.sessions_dir)
        session = manager.create_session_sync()
        manager.set_active_skill_ids(session.session_id, ["skill1", "skill2"])
        assert manager.get_active_skill_ids(session.session_id) == ["skill1", "skill2"]
        # SSOT lives only on session.active_skill_ids
        assert session.active_skill_ids == ["skill1", "skill2"]


class TestSessionManagerState:
    """Tests for state management."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_sessions_dir: Path) -> None:
        self.sessions_dir = tmp_sessions_dir

    def test_update_state(self) -> None:
        manager = SessionManager(self.sessions_dir)
        session = manager.create_session_sync()
        manager.update_state(session.session_id, {"key": "value"})
        assert manager.get_state(session.session_id)["key"] == "value"

    def test_get_session_stats(self) -> None:
        manager = SessionManager(self.sessions_dir)
        session = manager.create_session_sync()
        manager.add_message_sync(session.session_id, AgentMessage.user("Hello"))
        stats = manager.get_session_stats(session.session_id)
        assert stats["session_id"] == session.session_id
        assert stats["message_count"] == 1
        assert "estimated_tokens" in stats


class TestSessionManagerCompaction:
    """Tests for compaction."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_sessions_dir: Path) -> None:
        self.sessions_dir = tmp_sessions_dir

    def test_needs_compaction(self) -> None:
        manager = SessionManager(
            self.sessions_dir,
            compaction_config=CompactionConfig(
                context_window=100,
                output_reserve=10,
                system_reserve=10,
                trigger_threshold=0.5,
            ),
        )
        session = manager.create_session_sync()
        manager.add_message_sync(session.session_id, AgentMessage.user("Hi"))
        assert not manager.needs_compaction(session.session_id)

    @pytest.mark.asyncio
    async def test_compact_session(self) -> None:
        manager = SessionManager(
            self.sessions_dir,
            compaction_config=CompactionConfig(preserve_recent=1),
        )
        session = manager.create_session_sync()
        for i in range(5):
            manager.add_message_sync(session.session_id, AgentMessage.user(f"Message {i}"))
        result = await manager.compact_session(session.session_id, "test_user", force=True)
        assert result.original_count == 5


class TestSessionManagerPersistence:
    """Tests for session persistence."""

    USER_ID = "test_user"

    @pytest.mark.asyncio
    async def test_create_session_with_persistence(self, tmp_sessions_dir: Path) -> None:
        manager = SessionManager(sessions_dir=tmp_sessions_dir)
        session = await manager.create_session(self.USER_ID, model="test-model")
        assert session.session_id
        session_file = tmp_sessions_dir / self.USER_ID / f"{session.session_id}.jsonl"
        assert session_file.exists()

    @pytest.mark.asyncio
    async def test_add_message_with_persistence(self, tmp_sessions_dir: Path) -> None:
        manager = SessionManager(sessions_dir=tmp_sessions_dir)
        session = await manager.create_session(self.USER_ID)
        await manager.add_message(session.session_id, self.USER_ID, AgentMessage.user("Hello"))
        session_file = tmp_sessions_dir / self.USER_ID / f"{session.session_id}.jsonl"
        assert "Hello" in session_file.read_text()

    @pytest.mark.asyncio
    async def test_load_session(self, tmp_sessions_dir: Path) -> None:
        manager1 = SessionManager(sessions_dir=tmp_sessions_dir)
        session = await manager1.create_session(self.USER_ID)
        await manager1.add_message(session.session_id, self.USER_ID, AgentMessage.user("Test message"))

        manager2 = SessionManager(sessions_dir=tmp_sessions_dir)
        loaded = await manager2.load_session(session.session_id, self.USER_ID)
        assert loaded is not None
        assert len(loaded.messages) == 1
        assert loaded.messages[0].content == "Test message"

    @pytest.mark.asyncio
    async def test_delete_session_with_persistence(self, tmp_sessions_dir: Path) -> None:
        manager = SessionManager(sessions_dir=tmp_sessions_dir)
        session = await manager.create_session(self.USER_ID)
        session_file = tmp_sessions_dir / self.USER_ID / f"{session.session_id}.jsonl"
        assert session_file.exists()
        await manager.delete_session(session.session_id, self.USER_ID)
        assert not session_file.exists()


class TestRepositoryBackedPersistence:
    """Task 16 regressions: messages persist immediately, not via pending buffer."""

    USER_ID = "u1"

    async def test_add_message_persists_immediately(self, tmp_sessions_dir: Path) -> None:
        manager = SessionManager(sessions_dir=tmp_sessions_dir)
        session = await manager.create_session(self.USER_ID)

        await manager.add_message(
            session.session_id, self.USER_ID, AgentMessage.user("hello"),
        )

        # New SessionManager with same dir must see the message via repository.
        fresh = SessionManager(sessions_dir=tmp_sessions_dir)
        loaded = await fresh._repository.load_messages(session.session_id, self.USER_ID)
        assert any(m.content == "hello" for m in loaded), \
            "add_message must persist synchronously; pending-buffer is gone"


class TestEphemeralPathDoesNotPersist:
    async def test_add_message_in_memory_only_skips_disk(
        self, tmp_sessions_dir: Path,
    ) -> None:
        manager = SessionManager(sessions_dir=tmp_sessions_dir)
        session = manager.create_session_sync(user_id="u1")

        manager.add_message_in_memory_only(
            session.session_id, AgentMessage.user("ephemeral"),
        )

        # In-memory copy is updated...
        assert any(m.content == "ephemeral" for m in manager.get_messages(session.session_id))
        # ...but the repository was never touched.
        loaded = await manager._repository.load_messages(session.session_id, "u1")
        assert all(m.content != "ephemeral" for m in loaded)


class TestFinalizeIsCalled:
    USER_ID = "u-final"

    async def test_finalize_triggered_after_compact(
        self, tmp_sessions_dir: Path,
    ) -> None:
        manager = SessionManager(sessions_dir=tmp_sessions_dir)
        session = await manager.create_session(self.USER_ID)

        called: list[tuple[str, str]] = []
        original_finalize = manager._repository.finalize

        async def _spy(sid: str, uid: str) -> None:  # type: ignore[override]
            called.append((sid, uid))
            await original_finalize(sid, uid)

        manager._repository.finalize = _spy  # type: ignore[method-assign]

        await manager.compact_session(session.session_id, self.USER_ID, force=True)

        assert (session.session_id, self.USER_ID) in called
