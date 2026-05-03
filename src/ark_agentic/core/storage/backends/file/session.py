"""FileSessionRepository — wraps TranscriptManager + SessionStore.

PR2+ TODO: ``create()`` is a two-step non-atomic operation (header write +
meta upsert) under the file backend. DB implementations must wrap both steps
in a single transaction (or a UnitOfWork in PR2+).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from ....persistence import (
    SessionStore,
    SessionStoreEntry,
    TranscriptManager,
)
from ....types import AgentMessage


class FileSessionRepository:
    """File-backed implementation of SessionRepository."""

    def __init__(self, sessions_dir: str | Path) -> None:
        self._sessions_dir = Path(sessions_dir)
        self._transcript = TranscriptManager(self._sessions_dir)
        self._store = SessionStore(self._sessions_dir)

    async def create(
        self,
        session_id: str,
        user_id: str,
        model: str,
        provider: str,
        state: dict,
    ) -> None:
        # Two-step (PR2 SQLite must wrap in a transaction)
        await self._transcript.ensure_header(session_id, user_id)
        session_file = self._transcript._get_session_file(session_id, user_id)
        entry = SessionStoreEntry(
            session_id=session_id,
            updated_at=0,
            session_ref=str(session_file),
            model=model,
            provider=provider,
            state=state,
        )
        await self._store.update(user_id, session_id, entry)

    async def append_message(
        self,
        session_id: str,
        user_id: str,
        message: AgentMessage,
    ) -> None:
        await self._transcript.append_message(session_id, user_id, message)

    async def load_messages(
        self,
        session_id: str,
        user_id: str,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[AgentMessage]:
        # File 实现忽略 limit/offset; PR2 DB 实现 must enforce limit != None
        return await asyncio.to_thread(
            self._transcript.load_messages, session_id, user_id,
        )

    async def update_meta(
        self,
        session_id: str,
        user_id: str,
        entry: SessionStoreEntry,
    ) -> None:
        await self._store.update(user_id, session_id, entry)

    async def load_meta(
        self,
        session_id: str,
        user_id: str,
    ) -> SessionStoreEntry | None:
        return await asyncio.to_thread(self._store.get, user_id, session_id)

    async def list_session_ids(
        self,
        user_id: str,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[str]:
        # File 实现忽略 limit/offset; PR2 DB 实现 must enforce limit != None
        return await asyncio.to_thread(self._transcript.list_sessions, user_id)

    async def delete(
        self,
        session_id: str,
        user_id: str,
    ) -> bool:
        deleted = await asyncio.to_thread(
            self._transcript.delete_session, session_id, user_id,
        )
        await self._store.delete(user_id, session_id)
        return deleted

    async def get_raw_transcript(
        self,
        session_id: str,
        user_id: str,
    ) -> str | None:
        return await asyncio.to_thread(
            self._transcript.read_raw, session_id, user_id,
        )

    async def put_raw_transcript(
        self,
        session_id: str,
        user_id: str,
        jsonl_content: str,
    ) -> None:
        await self._transcript.write_raw(session_id, user_id, jsonl_content)

    async def finalize(
        self,
        session_id: str,
        user_id: str,
    ) -> None:
        """File backend: no-op. S3 backend (future) flushes buffer to object storage."""
        return None
