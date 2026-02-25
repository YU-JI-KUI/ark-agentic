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
from .persistence import SessionStore, SessionStoreEntry, TranscriptManager
from .types import AgentMessage, CompactionStats, SessionEntry, TokenUsage

logger = logging.getLogger(__name__)


class SessionManager:

    def __init__(
        self,
        compaction_config: CompactionConfig | None = None,
        sessions_dir: str | Path | None = None,
        enable_persistence: bool = True,
        summarizer: SummarizerProtocol | None = None,
    ) -> None:
        self._sessions: dict[str, SessionEntry] = {}
        self._compaction_config = compaction_config or CompactionConfig()
        self._compactor = ContextCompactor(self._compaction_config, summarizer=summarizer)

        # 持久化组件
        self._enable_persistence = enable_persistence
        if enable_persistence:
            self._transcript_manager = TranscriptManager(sessions_dir)
            self._session_store = SessionStore(
                Path(sessions_dir or Path.home() / ".ark_nav" / "sessions")
                / "sessions.json"
            )
        else:
            self._transcript_manager = None
            self._session_store = None

    # ============ 会话生命周期 ============

    async def create_session(
        self,
        model: str = "Qwen3-80B-Instruct",
        provider: str = "ark",
        metadata: dict[str, Any] | None = None,
    ) -> SessionEntry:
        """创建新会话"""
        session = SessionEntry.create(
            model=model, provider=provider, metadata=metadata or {}
        )
        self._sessions[session.session_id] = session

        # 持久化
        if self._enable_persistence and self._transcript_manager and self._session_store:
            await self._transcript_manager.ensure_header(session.session_id)
            store_entry = SessionStoreEntry(
                session_id=session.session_id,
                updated_at=int(session.updated_at.timestamp() * 1000),
                session_file=str(
                    self._transcript_manager._get_session_file(session.session_id)
                ),
                model=model,
                provider=provider,
                metadata=metadata or {},
            )
            await self._session_store.update(session.session_id, store_entry)

        logger.info(f"[SESSION_CREATE] id={session.session_id[:8]} model={model}")
        return session

    def create_session_sync(
        self,
        model: str = "Qwen3-80B-Instruct",
        provider: str = "ark",
        metadata: dict[str, Any] | None = None,
    ) -> SessionEntry:
        """同步创建新会话（不持久化，用于测试）"""
        session = SessionEntry.create(
            model=model, provider=provider, metadata=metadata or {}
        )
        self._sessions[session.session_id] = session
        logger.info(f"Created session (sync): {session.session_id}")
        return session

    def get_session(self, session_id: str) -> SessionEntry | None:
        """获取会话"""
        return self._sessions.get(session_id)

    def get_session_required(self, session_id: str) -> SessionEntry:
        """获取会话（必须存在）"""
        session = self.get_session(session_id)
        if session is None:
            raise KeyError(f"Session not found: {session_id}")
        return session

    async def delete_session(self, session_id: str) -> bool:
        """删除会话"""
        deleted = False
        if session_id in self._sessions:
            del self._sessions[session_id]
            deleted = True

        # 删除持久化数据
        if self._enable_persistence:
            if self._transcript_manager:
                self._transcript_manager.delete_session(session_id)
            if self._session_store:
                await self._session_store.delete(session_id)

        if deleted:
            logger.info(f"Deleted session: {session_id}")
        return deleted

    def delete_session_sync(self, session_id: str) -> bool:
        """同步删除会话（仅内存）"""
        if session_id in self._sessions:
            del self._sessions[session_id]
            logger.info(f"Deleted session (sync): {session_id}")
            return True
        return False

    def list_sessions(self) -> list[SessionEntry]:
        """列出所有会话"""
        return list(self._sessions.values())

    async def load_session(self, session_id: str) -> SessionEntry | None:
        """从持久化存储加载会话"""
        if not self._enable_persistence or not self._transcript_manager:
            return self.get_session(session_id)

        # 检查是否已在内存中
        if session_id in self._sessions:
            return self._sessions[session_id]

        # 从 JSONL 加载
        if not self._transcript_manager.session_exists(session_id):
            return None

        messages = self._transcript_manager.load_messages(session_id)
        header = self._transcript_manager.load_header(session_id)

        # 从元数据存储获取额外信息
        store_entry = None
        if self._session_store:
            store_entry = self._session_store.get(session_id)

        session = SessionEntry(
            session_id=session_id,
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
            metadata=store_entry.metadata if store_entry else {},
        )

        # 恢复 token 统计
        if store_entry:
            session.token_usage.prompt_tokens = store_entry.prompt_tokens
            session.token_usage.completion_tokens = store_entry.completion_tokens

        self._sessions[session_id] = session
        logger.info(f"Loaded session from disk: {session_id}")
        return session

    async def sync_pending_messages(self, session_id: str) -> None:
        """持久化待写入的消息"""
        if not self._enable_persistence or not self._transcript_manager:
            return

        session = self.get_session(session_id)
        if not session:
            return

        pending = getattr(session, "_pending_messages", [])
        if pending:
            await self._transcript_manager.append_messages(session_id, pending)
            session._pending_messages = []
            logger.debug(f"Synced {len(pending)} pending messages for session {session_id}")

    async def sync_session_metadata(self, session_id: str) -> None:
        """同步会话元数据和待写入消息到存储"""
        # 先同步待写入的消息
        await self.sync_pending_messages(session_id)

        if not self._enable_persistence or not self._session_store:
            return

        session = self.get_session(session_id)
        if not session:
            return

        store_entry = SessionStoreEntry(
            session_id=session.session_id,
            updated_at=int(session.updated_at.timestamp() * 1000),
            session_file=(
                str(self._transcript_manager._get_session_file(session_id))
                if self._transcript_manager
                else None
            ),
            model=session.model,
            provider=session.provider,
            prompt_tokens=session.token_usage.prompt_tokens,
            completion_tokens=session.token_usage.completion_tokens,
            total_tokens=session.token_usage.total_tokens,
            compaction_count=session.compaction_stats.compacted_messages,
            active_skills=session.active_skills,
            metadata=session.metadata,
        )

        await self._session_store.update(session_id, store_entry)

    # ============ 消息管理 ============

    async def add_message(self, session_id: str, message: AgentMessage) -> None:
        """添加消息到会话"""
        session = self.get_session_required(session_id)
        session.add_message(message)

        # 持久化
        if self._enable_persistence and self._transcript_manager:
            await self._transcript_manager.append_message(session_id, message)

        logger.debug(f"Added {message.role.value} message to session {session_id}")

    async def add_messages(self, session_id: str, messages: list[AgentMessage]) -> None:
        """批量添加消息"""
        session = self.get_session_required(session_id)
        for msg in messages:
            session.add_message(msg)

        # 批量持久化
        if self._enable_persistence and self._transcript_manager:
            await self._transcript_manager.append_messages(session_id, messages)

    def add_message_sync(self, session_id: str, message: AgentMessage) -> None:
        """同步添加消息（标记为待持久化）

        消息会立即加入内存，但持久化会延迟到 sync_pending_messages() 调用时。
        """
        session = self.get_session_required(session_id)
        session.add_message(message)
        # 标记有待持久化消息
        if not hasattr(session, "_pending_messages"):
            session._pending_messages = []
        session._pending_messages.append(message)
        logger.debug(f"Added {message.role.value} message to session {session_id} (pending sync)")

    def get_messages(
        self,
        session_id: str,
        include_system: bool = True,
        limit: int | None = None,
    ) -> list[AgentMessage]:
        """获取会话消息

        Args:
            session_id: 会话 ID
            include_system: 是否包含系统消息
            limit: 返回最近 N 条消息

        Returns:
            消息列表
        """
        session = self.get_session_required(session_id)
        messages = session.messages

        if not include_system:
            messages = [m for m in messages if m.role.value != "system"]

        if limit is not None and limit > 0:
            messages = messages[-limit:]

        return messages

    def clear_messages(self, session_id: str, keep_system: bool = True) -> None:
        """清空会话消息

        Args:
            session_id: 会话 ID
            keep_system: 是否保留系统消息
        """
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
        """获取 token 使用统计"""
        session = self.get_session_required(session_id)
        return session.token_usage

    def estimate_current_tokens(self, session_id: str) -> int:
        """估算当前会话的 token 数"""
        session = self.get_session_required(session_id)
        return sum(estimate_message_tokens(msg) for msg in session.messages)

    # ============ 上下文压缩 ============

    def needs_compaction(self, session_id: str) -> bool:
        """检查会话是否需要压缩"""
        session = self.get_session_required(session_id)
        return self._compactor.needs_compaction(session.messages)

    async def compact_session(
        self, session_id: str, force: bool = False
    ) -> CompactionResult:
        """压缩会话历史

        Args:
            session_id: 会话 ID
            force: 是否强制压缩

        Returns:
            压缩结果
        """
        session = self.get_session_required(session_id)

        result = await self._compactor.compact(session.messages, force=force)

        # 更新会话
        session.messages = result.messages
        session.updated_at = datetime.now()

        # 更新压缩统计
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

        # 同步元数据
        await self.sync_session_metadata(session_id)

        return result

    async def auto_compact_if_needed(
        self,
        session_id: str,
        pre_compact_callback: Callable[[str, list[AgentMessage]], Awaitable[None]] | None = None,
    ) -> CompactionResult | None:
        """自动检查并压缩（如果需要）

        Args:
            session_id: 会话 ID
            pre_compact_callback: 压缩前回调（用于 memory flush 等），
                签名: async (session_id, messages) -> None
        """
        if self.needs_compaction(session_id):
            # 压缩前回调（允许 Agent 将重要上下文写入 memory）
            if pre_compact_callback is not None:
                try:
                    session = self.get_session_required(session_id)
                    await pre_compact_callback(session_id, session.messages)
                except Exception as e:
                    logger.warning(f"Pre-compaction callback failed: {e}")

            return await self.compact_session(session_id)
        return None

    # ============ 技能管理 ============

    def set_active_skills(self, session_id: str, skill_ids: list[str]) -> None:
        """设置会话的活跃技能"""
        session = self.get_session_required(session_id)
        session.active_skills = skill_ids
        session.updated_at = datetime.now()

    def get_active_skills(self, session_id: str) -> list[str]:
        """获取会话的活跃技能"""
        session = self.get_session_required(session_id)
        return session.active_skills

    # ============ 元数据 ============

    def update_metadata(self, session_id: str, metadata: dict[str, Any]) -> None:
        """更新会话元数据"""
        session = self.get_session_required(session_id)
        session.metadata.update(metadata)
        session.updated_at = datetime.now()

    def get_metadata(self, session_id: str) -> dict[str, Any]:
        """获取会话元数据"""
        session = self.get_session_required(session_id)
        return session.metadata

    # ============ 统计信息 ============

    def get_session_stats(self, session_id: str) -> dict[str, Any]:
        """获取会话统计信息"""
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
