"""SessionManager — message tracking, compaction, persistence (via repo)."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from .compaction import (
    CompactionConfig,
    CompactionResult,
    ContextCompactor,
    SummarizerProtocol,
    estimate_message_tokens,
)
from .history_merge import InsertOp
from .persistence import SessionStoreEntry
from .types import AgentMessage, CompactionStats, SessionEntry, TokenUsage

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

    from .storage.protocols import SessionRepository

logger = logging.getLogger(__name__)


class SessionManager:
    """Per-agent session orchestrator backed by a single ``SessionRepository``.

    Storage details (file vs. SQLite) live entirely behind the repository; this
    class never imports backend-specific types or paths. ``sessions_dir`` is
    surfaced as a public attribute for non-storage callers (proactive job
    scanner) that still need a workspace root under file mode.
    """

    def __init__(
        self,
        sessions_dir: str | Path,
        compaction_config: CompactionConfig | None = None,
        summarizer: SummarizerProtocol | None = None,
        repository: "SessionRepository | None" = None,
        db_engine: "AsyncEngine | None" = None,
    ) -> None:
        self._sessions: dict[str, SessionEntry] = {}
        self._compaction_config = compaction_config or CompactionConfig()
        self._compactor = ContextCompactor(
            self._compaction_config, summarizer=summarizer
        )
        self.sessions_dir = Path(sessions_dir)
        if repository is None:
            from .storage.factory import build_session_repository

            repository = build_session_repository(
                sessions_dir=sessions_dir, engine=db_engine,
            )
        self._repository = repository

    @property
    def repository(self) -> "SessionRepository":
        return self._repository

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

        # repository.create() owns whatever "create" means for the active
        # backend (file: write JSONL header + sessions.json; SQLite: INSERT
        # session_meta with ON CONFLICT DO NOTHING).
        await self._repository.create(
            session.session_id, user_id, model, provider, state or {},
        )
        # Stamp updated_at to "now" so list ordering reflects creation order
        # before the first message lands.
        await self._repository.update_meta(
            session.session_id,
            user_id,
            SessionStoreEntry(
                session_id=session.session_id,
                updated_at=int(session.updated_at.timestamp() * 1000),
                model=model,
                provider=provider,
                state=state or {},
            ),
        )

        logger.info(
            "[SESSION_CREATE] id=%s user=%s model=%s",
            session.session_id[:8], user_id, model,
        )
        return session

    def create_session_sync(
        self,
        model: str = "Qwen3-80B-Instruct",
        provider: str = "ark",
        state: dict[str, Any] | None = None,
        session_id: str | None = None,
        user_id: str | None = None,
    ) -> SessionEntry:
        """同步创建（仅写入内存，不落盘；需持久化请用 create_session）"""
        session = SessionEntry.create(
            model=model, provider=provider, state=state or {}
        )
        if session_id is not None:
            session.session_id = session_id
        if user_id is not None:
            session.user_id = user_id
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
        in_memory = session_id in self._sessions
        if in_memory:
            del self._sessions[session_id]

        # Repository delete is idempotent across backends and returns whether
        # any persisted row was actually removed.
        persisted_deleted = await self._repository.delete(session_id, user_id)

        deleted = in_memory or persisted_deleted
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
        """List in-memory sessions only."""
        return list(self._sessions.values())

    async def list_sessions_from_disk(
        self, user_id: str | None = None,
    ) -> list[SessionEntry]:
        """List sessions from persistent storage.

        ``user_id=None`` lists every user's sessions (admin view).
        """
        if user_id is not None:
            ids = await self._repository.list_session_ids(user_id)
            return await self._collect_sessions(
                [(user_id, sid) for sid in ids]
            )

        pairs = await self._repository.list_all_sessions()
        return await self._collect_sessions(pairs)

    async def _collect_sessions(
        self, pairs: list[tuple[str, str]],
    ) -> list[SessionEntry]:
        result: list[SessionEntry] = []
        for uid, sid in pairs:
            entry = await self.load_session(sid, uid)
            if entry is not None:
                result.append(entry)
        return result

    async def reload_session_from_disk(
        self, session_id: str, user_id: str,
    ) -> SessionEntry | None:
        """Reload an already-tracked session from storage. No-op if untracked."""
        if session_id not in self._sessions:
            return None
        return await self._build_session_from_storage(session_id, user_id)

    async def load_session(
        self, session_id: str, user_id: str,
    ) -> SessionEntry | None:
        """Return the in-memory session if cached; otherwise hydrate from storage."""
        if session_id in self._sessions:
            entry = self._sessions[session_id]
            entry.user_id = user_id
            return entry
        return await self._build_session_from_storage(session_id, user_id)

    async def _build_session_from_storage(
        self, session_id: str, user_id: str,
    ) -> SessionEntry | None:
        store_entry = await self._repository.load_meta(session_id, user_id)
        if store_entry is None:
            return None
        messages = await self._repository.load_messages(session_id, user_id)

        # ``created_at`` is not currently persisted as a distinct column —
        # we approximate it from ``updated_at`` (or "now" for fresh rows
        # whose updated_at is still 0).
        ts = (
            datetime.fromtimestamp(store_entry.updated_at / 1000)
            if store_entry.updated_at
            else datetime.now()
        )

        session = SessionEntry(
            session_id=session_id,
            user_id=user_id,
            created_at=ts,
            updated_at=ts,
            model=store_entry.model,
            provider=store_entry.provider,
            messages=messages,
            active_skill_ids=store_entry.active_skill_ids,
            state=store_entry.state,
        )
        session.token_usage.prompt_tokens = store_entry.prompt_tokens
        session.token_usage.completion_tokens = store_entry.completion_tokens

        self._sessions[session_id] = session
        logger.debug(f"Loaded session from storage: {session_id}")
        return session

    async def sync_pending_messages(self, session_id: str, user_id: str) -> None:
        """Deprecated no-op. ``add_message`` persists synchronously now.

        Kept so legacy call sites still compile; remove in a follow-up PR.
        """
        return None

    async def sync_session_state(self, session_id: str, user_id: str) -> None:
        session = self.get_session(session_id)
        if not session:
            return

        store_entry = SessionStoreEntry(
            session_id=session.session_id,
            updated_at=int(session.updated_at.timestamp() * 1000),
            model=session.model,
            provider=session.provider,
            prompt_tokens=session.token_usage.prompt_tokens,
            completion_tokens=session.token_usage.completion_tokens,
            total_tokens=session.token_usage.total_tokens,
            compaction_count=session.compaction_stats.compacted_messages,
            active_skill_ids=session.active_skill_ids,
            state=session.state,
        )
        await self._repository.update_meta(session_id, user_id, store_entry)

    # ============ 消息管理 ============

    async def add_message(
        self, session_id: str, user_id: str, message: AgentMessage,
    ) -> None:
        session = self.get_session_required(session_id)
        session.add_message(message)

        await self._repository.append_message(session_id, user_id, message)
        logger.debug(
            f"Added {message.role.value} message to session {session_id}"
        )

    async def add_messages(
        self, session_id: str, user_id: str, messages: list[AgentMessage],
    ) -> None:
        session = self.get_session_required(session_id)
        for msg in messages:
            session.add_message(msg)

        for msg in messages:
            await self._repository.append_message(session_id, user_id, msg)

    def add_message_in_memory_only(
        self, session_id: str, message: AgentMessage,
    ) -> None:
        """Ephemeral path. Writes only to the in-memory session; never persists.

        Used by ``run_ephemeral`` to preserve the previous "ephemeral does not
        touch disk" contract under the new repository-backed pipeline.
        """
        session = self.get_session_required(session_id)
        session.add_message(message)
        logger.debug(
            f"Added {message.role.value} message to session "
            f"{session_id} (in-memory only)"
        )

    def add_message_sync(self, session_id: str, message: AgentMessage) -> None:
        """Deprecated alias for ``add_message_in_memory_only``."""
        self.add_message_in_memory_only(session_id, message)

    async def inject_messages(
        self, session_id: str, user_id: str, ops: list[InsertOp],
    ) -> None:
        """Insert external-history messages at anchor-resolved positions."""
        if not ops:
            return
        session = self.get_session_required(session_id)

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

        # Append in forward order so persistence is chronological
        for _, msg in resolved:
            await self._repository.append_message(session_id, user_id, msg)

        session.updated_at = datetime.now()
        logger.info(
            f"Injected {len(ops)} external message(s) into session "
            f"{session_id[:8]}"
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
            session.messages = [
                m for m in session.messages if m.role.value == "system"
            ]
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
        session.update_token_usage(
            prompt_tokens, completion_tokens, cache_read, cache_creation,
        )

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
        self, session_id: str, user_id: str, force: bool = False,
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
        await self.finalize_session(session_id, user_id)

        return result

    async def finalize_session(self, session_id: str, user_id: str) -> None:
        """Mark the session ready for archival.

        File/SQLite/PG: no-op. S3 (future): flush in-memory buffer to object
        storage. Callers should invoke this after a turn settles or after
        ``compact_session`` so the future S3 backend can release its buffer.
        """
        await self._repository.finalize(session_id, user_id)

    async def auto_compact_if_needed(
        self,
        session_id: str,
        user_id: str,
        pre_compact_callback: (
            Callable[[str, list[AgentMessage]], Awaitable[None]] | None
        ) = None,
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

    def set_active_skill_ids(
        self, session_id: str, skill_ids: list[str],
    ) -> None:
        """覆盖式写入 session.active_skill_ids（SSOT）。

        full 模式 session 的此字段会在 `_run_turn` 顶部每轮被 clobber 为
        所有已加载 skill；外部覆盖在下轮失效。
        """
        session = self.get_session_required(session_id)
        session.set_active_skill_ids(skill_ids)

    def get_active_skill_ids(self, session_id: str) -> list[str]:
        session = self.get_session_required(session_id)
        return session.active_skill_ids

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
            "active_skill_ids": session.active_skill_ids,
        }
