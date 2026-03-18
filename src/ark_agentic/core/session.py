"""会话管理器: 消息追踪、压缩、持久化"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Awaitable

from .compaction import (
    CompactionConfig,
    CompactionResult,
    ContextCompactor,
    SummarizerProtocol,
    estimate_message_tokens,
)
from .history_merge import InsertOp
from .persistence import SessionStore, SessionStoreEntry, TranscriptManager
from .types import AgentMessage, CompactionStats, SessionEntry, TokenUsage

logger = logging.getLogger(__name__)


class SessionManager:

    def __init__(
        self,
        sessions_dir: str | Path,
        compaction_config: CompactionConfig | None = None,
        summarizer: SummarizerProtocol | None = None,
    ) -> None:
        self._sessions: dict[str, SessionEntry] = {}
        self._compaction_config = compaction_config or CompactionConfig()
        self._compactor = ContextCompactor(self._compaction_config, summarizer=summarizer)
        self._transcript_manager = TranscriptManager(sessions_dir)
        self._session_store = SessionStore(sessions_dir)

    # ============ 会话生命周期 ============

    async def create_session(
        self,
        user_id: str,
        model: str = "Qwen3-80B-Instruct",
        provider: str = "ark",
        state: dict[str, Any] | None = None,
    ) -> SessionEntry:
        session = SessionEntry.create(
            model=model, provider=provider, state=state or {}
        )
        session.user_id = user_id
        self._sessions[session.session_id] = session

        await self._transcript_manager.ensure_header(session.session_id, user_id)
        store_entry = SessionStoreEntry(
            session_id=session.session_id,
            updated_at=int(session.updated_at.timestamp() * 1000),
            session_file=str(
                self._transcript_manager._get_session_file(session.session_id, user_id)
            ),
            model=model,
            provider=provider,
            state=state or {},
        )
        await self._session_store.update(user_id, session.session_id, store_entry)

        logger.info(f"[SESSION_CREATE] id={session.session_id[:8]} user={user_id} model={model}")
        return session

    def create_session_sync(
        self,
        model: str = "Qwen3-80B-Instruct",
        provider: str = "ark",
        state: dict[str, Any] | None = None,
    ) -> SessionEntry:
        """同步创建新会话（仅写入内存，不落盘；需持久化请用 create_session）"""
        session = SessionEntry.create(
            model=model, provider=provider, state=state or {}
        )
        self._sessions[session.session_id] = session
        logger.info(f"Created session (sync): {session.session_id}")
        return session

    def get_session(self, session_id: str) -> SessionEntry | None:
        return self._sessions.get(session_id)

    def get_session_required(self, session_id: str) -> SessionEntry:
        session = self.get_session(session_id)
        if session is None:
            raise KeyError(f"Session not found: {session_id}")
        return session

    async def delete_session(self, session_id: str, user_id: str) -> bool:
        deleted = False
        if session_id in self._sessions:
            del self._sessions[session_id]
            deleted = True

        self._transcript_manager.delete_session(session_id, user_id)
        await self._session_store.delete(user_id, session_id)

        if deleted:
            logger.info(f"Deleted session: {session_id}")
        return deleted

    def delete_session_sync(self, session_id: str) -> bool:
        if session_id in self._sessions:
            del self._sessions[session_id]
            logger.info(f"Deleted session (sync): {session_id}")
            return True
        return False

    def list_sessions(self) -> list[SessionEntry]:
        """列出所有会话（仅内存）。"""
        return list(self._sessions.values())

    async def list_sessions_from_disk(self, user_id: str | None = None) -> list[SessionEntry]:
        """以磁盘为准列出会话。user_id=None 时列出所有用户的会话（admin）。"""
        if user_id is not None:
            ids = self._transcript_manager.list_sessions(user_id)
            result: list[SessionEntry] = []
            for sid in ids:
                entry = await self.load_session(sid, user_id)
                if entry is not None:
                    result.append(entry)
            return result

        pairs = self._transcript_manager.list_all_sessions()
        result = []
        for uid, sid in pairs:
            entry = await self.load_session(sid, uid)
            if entry is not None:
                result.append(entry)
        return result

    async def reload_session_from_disk(self, session_id: str, user_id: str) -> SessionEntry | None:
        if session_id not in self._sessions:
            return None
        if not self._transcript_manager.session_exists(session_id, user_id):
            return None
        messages = self._transcript_manager.load_messages(session_id, user_id)
        header = self._transcript_manager.load_header(session_id, user_id)
        store_entry = self._session_store.get(user_id, session_id)
        session = SessionEntry(
            session_id=session_id,
            user_id=user_id,
            created_at=(
                datetime.fromisoformat(header.timestamp)
                if header and header.timestamp
                else datetime.now()
            ),
            updated_at=datetime.now(),
            model=store_entry.model if store_entry else "Qwen3-80B-Instruct",
            provider=store_entry.provider if store_entry else "ark",
            messages=messages,
            active_skills=store_entry.active_skills if store_entry else [],
            state=store_entry.state if store_entry else {},
        )
        if store_entry:
            session.token_usage.prompt_tokens = store_entry.prompt_tokens
            session.token_usage.completion_tokens = store_entry.completion_tokens
        self._sessions[session_id] = session
        logger.debug(f"Reloaded session from disk: {session_id}")
        return session

    async def load_session(self, session_id: str, user_id: str) -> SessionEntry | None:
        if session_id in self._sessions:
            entry = self._sessions[session_id]
            entry.user_id = user_id
            return entry

        if not self._transcript_manager.session_exists(session_id, user_id):
            return None

        messages = self._transcript_manager.load_messages(session_id, user_id)
        header = self._transcript_manager.load_header(session_id, user_id)
        store_entry = self._session_store.get(user_id, session_id)

        session = SessionEntry(
            session_id=session_id,
            user_id=user_id,
            created_at=(
                datetime.fromisoformat(header.timestamp)
                if header and header.timestamp
                else datetime.now()
            ),
            updated_at=datetime.now(),
            model=store_entry.model if store_entry else "Qwen3-80B-Instruct",
            provider=store_entry.provider if store_entry else "ark",
            messages=messages,
            active_skills=store_entry.active_skills if store_entry else [],
            state=store_entry.state if store_entry else {},
        )

        if store_entry:
            session.token_usage.prompt_tokens = store_entry.prompt_tokens
            session.token_usage.completion_tokens = store_entry.completion_tokens

        self._sessions[session_id] = session
        logger.info(f"Loaded session from disk: {session_id}")
        return session

    async def sync_pending_messages(self, session_id: str, user_id: str) -> None:
        session = self.get_session(session_id)
        if not session:
            return

        pending = getattr(session, "_pending_messages", [])
        if pending:
            await self._transcript_manager.append_messages(session_id, user_id, pending)
            session._pending_messages = []
            logger.debug(f"Synced {len(pending)} pending messages for session {session_id}")

    async def sync_session_state(self, session_id: str, user_id: str) -> None:
        await self.sync_pending_messages(session_id, user_id)

        session = self.get_session(session_id)
        if not session:
            return

        store_entry = SessionStoreEntry(
            session_id=session.session_id,
            updated_at=int(session.updated_at.timestamp() * 1000),
            session_file=str(self._transcript_manager._get_session_file(session_id, user_id)),
            model=session.model,
            provider=session.provider,
            prompt_tokens=session.token_usage.prompt_tokens,
            completion_tokens=session.token_usage.completion_tokens,
            total_tokens=session.token_usage.total_tokens,
            compaction_count=session.compaction_stats.compacted_messages,
            active_skills=session.active_skills,
            state=session.state,
        )

        await self._session_store.update(user_id, session_id, store_entry)

    # ============ 消息管理 ============

    async def add_message(self, session_id: str, user_id: str, message: AgentMessage) -> None:
        session = self.get_session_required(session_id)
        session.add_message(message)

        await self._transcript_manager.append_message(session_id, user_id, message)
        logger.debug(f"Added {message.role.value} message to session {session_id}")

    async def add_messages(self, session_id: str, user_id: str, messages: list[AgentMessage]) -> None:
        session = self.get_session_required(session_id)
        for msg in messages:
            session.add_message(msg)

        await self._transcript_manager.append_messages(session_id, user_id, messages)

    def add_message_sync(self, session_id: str, message: AgentMessage) -> None:
        """同步添加消息（标记为待持久化）

        消息会立即加入内存，但持久化会延迟到 sync_pending_messages() 调用时。
        """
        session = self.get_session_required(session_id)
        session.add_message(message)
        if not hasattr(session, "_pending_messages"):
            session._pending_messages = []
        session._pending_messages.append(message)
        logger.debug(f"Added {message.role.value} message to session {session_id} (pending sync)")

    def inject_messages(self, session_id: str, ops: list[InsertOp]) -> None:
        """Insert external-history messages at anchor-resolved positions.

        Each :class:`InsertOp` carries a semantic anchor (timestamp ISO key).
        This method resolves it to an actual index in ``session.messages``,
        performs the insertion, and marks the message as pending for persistence.
        """
        if not ops:
            return
        session = self.get_session_required(session_id)
        if not hasattr(session, "_pending_messages"):
            session._pending_messages = []

        resolved: list[tuple[int, AgentMessage]] = []
        for op in ops:
            if op.anchor_message_id is None:
                idx = len(session.messages)
            else:
                anchor_idx = next(
                    (
                        i
                        for i, m in enumerate(session.messages)
                        if m.timestamp.isoformat() == op.anchor_message_id
                    ),
                    len(session.messages),
                )
                idx = anchor_idx if op.insert_before else anchor_idx + 1
            resolved.append((idx, op.message))

        # When multiple ops share the same idx (e.g. all anchor=None → append),
        # reversed insertion preserves forward order: last op inserts first and
        # gets pushed rightward by subsequent insertions.
        for idx, msg in reversed(resolved):
            session.messages.insert(idx, msg)

        # Append in forward order so JSONL persistence is chronological
        for _, msg in resolved:
            session._pending_messages.append(msg)

        session.updated_at = datetime.now()
        logger.info(
            f"Injected {len(ops)} external message(s) into session {session_id[:8]}"
        )

    def get_messages(
        self,
        session_id: str,
        include_system: bool = True,
        limit: int | None = None,
    ) -> list[AgentMessage]:
        session = self.get_session_required(session_id)
        messages = session.messages

        if not include_system:
            messages = [m for m in messages if m.role.value != "system"]

        if limit is not None and limit > 0:
            messages = messages[-limit:]

        return messages

    def clear_messages(self, session_id: str, keep_system: bool = True) -> None:
        session = self.get_session_required(session_id)
        if keep_system:
            session.messages = [m for m in session.messages if m.role.value == "system"]
        else:
            session.messages = []
        session.updated_at = datetime.now()

    # ============ Token 统计 ============

    def update_token_usage(
        self,
        session_id: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        cache_read: int = 0,
        cache_creation: int = 0,
    ) -> None:
        session = self.get_session_required(session_id)
        session.update_token_usage(prompt_tokens, completion_tokens, cache_read, cache_creation)

    def get_token_usage(self, session_id: str) -> TokenUsage:
        session = self.get_session_required(session_id)
        return session.token_usage

    def estimate_current_tokens(self, session_id: str) -> int:
        session = self.get_session_required(session_id)
        return sum(estimate_message_tokens(msg) for msg in session.messages)

    # ============ 上下文压缩 ============

    def needs_compaction(self, session_id: str) -> bool:
        session = self.get_session_required(session_id)
        return self._compactor.needs_compaction(session.messages)

    async def compact_session(
        self, session_id: str, user_id: str, force: bool = False
    ) -> CompactionResult:
        session = self.get_session_required(session_id)

        result = await self._compactor.compact(session.messages, force=force)

        session.messages = result.messages
        session.updated_at = datetime.now()

        session.compaction_stats = CompactionStats(
            original_messages=result.original_count,
            compacted_messages=result.compacted_count,
            original_tokens=result.original_tokens,
            compacted_tokens=result.compacted_tokens,
            last_compaction_at=datetime.now(),
        )

        logger.info(
            f"Compacted session {session_id}: "
            f"{result.original_count} -> {result.compacted_count} messages, "
            f"{result.original_tokens} -> {result.compacted_tokens} tokens"
        )

        await self.sync_session_state(session_id, user_id)

        return result

    async def auto_compact_if_needed(
        self,
        session_id: str,
        user_id: str,
        pre_compact_callback: Callable[[str, list[AgentMessage]], Awaitable[None]] | None = None,
    ) -> CompactionResult | None:
        if self.needs_compaction(session_id):
            if pre_compact_callback is not None:
                try:
                    session = self.get_session_required(session_id)
                    await pre_compact_callback(session_id, session.messages)
                except Exception as e:
                    logger.warning(f"Pre-compaction callback failed: {e}")

            return await self.compact_session(session_id, user_id)
        return None

    # ============ 技能管理 ============

    def set_active_skills(self, session_id: str, skill_ids: list[str]) -> None:
        session = self.get_session_required(session_id)
        session.active_skills = skill_ids
        session.updated_at = datetime.now()

    def get_active_skills(self, session_id: str) -> list[str]:
        session = self.get_session_required(session_id)
        return session.active_skills

    # ============ 状态管理 ============

    def update_state(self, session_id: str, state: dict[str, Any]) -> None:
        session = self.get_session_required(session_id)
        session.state.update(state)
        session.updated_at = datetime.now()

    def get_state(self, session_id: str) -> dict[str, Any]:
        session = self.get_session_required(session_id)
        return session.state

    # ============ 统计信息 ============

    def get_session_stats(self, session_id: str) -> dict[str, Any]:
        session = self.get_session_required(session_id)
        return {
            "session_id": session.session_id,
            "created_at": session.created_at.isoformat(),
            "updated_at": session.updated_at.isoformat(),
            "model": session.model,
            "provider": session.provider,
            "message_count": len(session.messages),
            "estimated_tokens": self.estimate_current_tokens(session_id),
            "token_usage": {
                "input": session.token_usage.prompt_tokens,
                "output": session.token_usage.completion_tokens,
                "total": session.token_usage.total_tokens,
            },
            "compaction": {
                "original_messages": session.compaction_stats.original_messages,
                "compacted_messages": session.compaction_stats.compacted_messages,
                "last_compaction": (
                    session.compaction_stats.last_compaction_at.isoformat()
                    if session.compaction_stats.last_compaction_at
                    else None
                ),
            },
            "active_skills": session.active_skills,
        }
