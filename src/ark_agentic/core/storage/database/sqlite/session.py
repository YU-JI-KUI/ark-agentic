"""SqliteSessionRepository — SQLAlchemy AsyncEngine implementation.

Bound to one ``agent_id`` at construction; ORM statements run inside
``agent_scoped_session`` so ``WHERE agent_id = :bound`` is auto-injected
on SELECT/UPDATE/DELETE. ``user_id`` ownership is still checked
explicitly — the file backend has the same semantics.

PR3 PG TODO:
- ``load_messages(limit=None)`` should raise on PG (forces pagination).
- ``json_extract`` in ``_summary_stmt`` is SQLite-only; PG needs
  ``payload_json::jsonb ->> 'role'``.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from ..models import SessionMessage, SessionMeta
from ..scoping import agent_scoped_session
from ....session.format import (
    MessageEntry,
    RawJsonlValidationError,
    SessionHeader,
    deserialize_message,
    parse_raw_jsonl,
    serialize_message,
)
from ...entries import SessionStoreEntry, SessionSummaryEntry
from ....types import AgentMessage


def _extract_first_text(payload_json: str | None) -> str | None:
    """Pull a 80-char snippet from the first text block of a message payload.

    ``payload_json`` is the value of ``session_messages.payload_json``,
    written by ``serialize_message`` — content is a list of typed blocks
    (``[{type: text, text: ...}, ...]``). Legacy rows that stored content
    as a plain string are also handled.
    """
    if not payload_json:
        return None
    try:
        payload = json.loads(payload_json)
    except (json.JSONDecodeError, TypeError):
        return None
    content = payload.get("content") if isinstance(payload, dict) else None
    if isinstance(content, str):
        return content[:80] or None
    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") != "text":
                continue
            text = block.get("text")
            if isinstance(text, str) and text:
                return text[:80]
    return None


class SqliteSessionRepository:
    """SessionRepository over a SQLAlchemy AsyncEngine, bound to one agent."""

    def __init__(self, engine: AsyncEngine, agent_id: str) -> None:
        if not agent_id:
            raise ValueError("SqliteSessionRepository requires a non-empty agent_id")
        self._engine = engine
        self._agent_id = agent_id
        self._sessionmaker = async_sessionmaker(engine, expire_on_commit=False)

    # ── SessionRepository methods ───────────────────────────────────

    async def create(
        self,
        session_id: str,
        user_id: str,
        model: str,
        provider: str,
        state: dict,
    ) -> None:
        # ON CONFLICT DO NOTHING avoids the SELECT-then-INSERT race; the
        # composite PK (agent_id, session_id) is the conflict target.
        stmt = sqlite_insert(SessionMeta).values(
            session_id=session_id,
            user_id=user_id,
            updated_at=0,
            model=model,
            provider=provider,
            state_json=json.dumps(state, ensure_ascii=False),
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            compaction_count=0,
            active_skill_ids_json="[]",
        ).on_conflict_do_nothing(index_elements=["agent_id", "session_id"])
        async with agent_scoped_session(self._sessionmaker, self._agent_id) as s:
            await s.execute(stmt)
            await s.commit()

    async def append_message(
        self,
        session_id: str,
        user_id: str,
        message: AgentMessage,
    ) -> None:
        """Append with next seq. Caller must serialise appends per session_id;
        concurrent appends rely on the unique index to reject duplicates."""
        payload = json.dumps(serialize_message(message), ensure_ascii=False)
        ts_ms = int(message.timestamp.timestamp() * 1000)
        async with agent_scoped_session(self._sessionmaker, self._agent_id) as s:
            next_seq = await s.scalar(
                select(func.coalesce(func.max(SessionMessage.seq), -1) + 1)
                .where(
                    SessionMessage.session_id == session_id,
                    SessionMessage.user_id == user_id,
                )
            )
            await s.execute(
                sqlite_insert(SessionMessage).values(
                    session_id=session_id,
                    user_id=user_id,
                    seq=next_seq,
                    payload_json=payload,
                    timestamp=ts_ms,
                )
            )
            await s.commit()

    async def load_messages(
        self,
        session_id: str,
        user_id: str,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[AgentMessage]:
        """SQLite tolerates ``limit=None``; PR3 PG must raise on hot path."""
        stmt = (
            select(SessionMessage.payload_json)
            .where(
                SessionMessage.session_id == session_id,
                SessionMessage.user_id == user_id,
            )
            .order_by(SessionMessage.seq.asc())
        )
        if limit is not None:
            stmt = stmt.limit(limit).offset(offset)
        async with agent_scoped_session(self._sessionmaker, self._agent_id) as s:
            rows = (await s.execute(stmt)).all()
        return [deserialize_message(json.loads(r[0])) for r in rows]

    async def update_meta(
        self,
        session_id: str,
        user_id: str,
        entry: SessionStoreEntry,
    ) -> None:
        values = {
            "user_id": user_id,
            "updated_at": entry.updated_at,
            "model": entry.model,
            "provider": entry.provider,
            "state_json": json.dumps(entry.state, ensure_ascii=False),
            "prompt_tokens": entry.prompt_tokens,
            "completion_tokens": entry.completion_tokens,
            "total_tokens": entry.total_tokens,
            "compaction_count": entry.compaction_count,
            "active_skill_ids_json": json.dumps(
                entry.active_skill_ids, ensure_ascii=False,
            ),
        }
        # Composite PK (agent_id, session_id) keeps cross-agent rows
        # separate — without it this set_ would rewrite another agent's row.
        stmt = sqlite_insert(SessionMeta).values(
            session_id=session_id,
            agent_id=self._agent_id,
            **values,
        ).on_conflict_do_update(
            index_elements=["agent_id", "session_id"],
            set_=values,
        )
        async with agent_scoped_session(self._sessionmaker, self._agent_id) as s:
            await s.execute(stmt)
            await s.commit()

    async def load_meta(
        self,
        session_id: str,
        user_id: str,
    ) -> SessionStoreEntry | None:
        async with agent_scoped_session(self._sessionmaker, self._agent_id) as s:
            row = (await s.execute(
                select(SessionMeta).where(
                    SessionMeta.session_id == session_id,
                    SessionMeta.user_id == user_id,
                )
            )).scalar_one_or_none()
        return self._row_to_entry(row) if row is not None else None

    async def list_session_ids(
        self,
        user_id: str,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[str]:
        stmt = (
            select(SessionMeta.session_id)
            .where(SessionMeta.user_id == user_id)
            .order_by(SessionMeta.updated_at.desc())
        )
        if limit is not None:
            stmt = stmt.limit(limit).offset(offset)
        async with agent_scoped_session(self._sessionmaker, self._agent_id) as s:
            rows = (await s.execute(stmt)).all()
        return [r[0] for r in rows]

    async def list_session_metas(
        self,
        user_id: str,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[SessionStoreEntry]:
        stmt = (
            select(SessionMeta)
            .where(SessionMeta.user_id == user_id)
            .order_by(SessionMeta.updated_at.desc())
        )
        if limit is not None:
            stmt = stmt.limit(limit).offset(offset)
        async with agent_scoped_session(self._sessionmaker, self._agent_id) as s:
            rows = (await s.execute(stmt)).scalars().all()
        return [self._row_to_entry(r) for r in rows]

    async def list_all_sessions(
        self,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[tuple[str, str]]:
        """``(user_id, session_id)`` for every user under THIS agent."""
        stmt = (
            select(SessionMeta.user_id, SessionMeta.session_id)
            .order_by(SessionMeta.updated_at.desc())
        )
        if limit is not None:
            stmt = stmt.limit(limit).offset(offset)
        async with agent_scoped_session(self._sessionmaker, self._agent_id) as s:
            rows = (await s.execute(stmt)).all()
        return [(r[0], r[1]) for r in rows]

    async def list_session_summaries(
        self,
        user_id: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[SessionSummaryEntry]:
        """``user_id=None`` returns all users under THIS agent."""
        stmt = self._summary_stmt()
        if user_id is not None:
            stmt = stmt.where(SessionMeta.user_id == user_id)
        if limit is not None:
            stmt = stmt.limit(limit).offset(offset)
        async with agent_scoped_session(self._sessionmaker, self._agent_id) as s:
            rows = (await s.execute(stmt)).all()
        return [self._row_to_summary(r) for r in rows]

    @staticmethod
    def _summary_stmt() -> Any:
        """Per-session count + first-user-message snippet via correlated
        scalar subqueries. SessionMessage refs pick up the agent filter."""
        mc = (
            select(func.count(SessionMessage.id))
            .where(SessionMessage.session_id == SessionMeta.session_id)
            .correlate(SessionMeta)
            .scalar_subquery()
        )
        fum = (
            select(SessionMessage.payload_json)
            .where(
                SessionMessage.session_id == SessionMeta.session_id,
                func.json_extract(
                    SessionMessage.payload_json, "$.role",
                ) == "user",
            )
            .order_by(SessionMessage.seq.asc())
            .limit(1)
            .correlate(SessionMeta)
            .scalar_subquery()
        )
        return (
            select(
                SessionMeta.session_id,
                SessionMeta.user_id,
                SessionMeta.updated_at,
                SessionMeta.model,
                SessionMeta.provider,
                SessionMeta.state_json,
                mc.label("mc"),
                fum.label("fum"),
            )
            .order_by(SessionMeta.updated_at.desc())
        )

    @staticmethod
    def _row_to_summary(row: Any) -> SessionSummaryEntry:
        snippet = _extract_first_text(row.fum)
        return SessionSummaryEntry(
            session_id=row.session_id,
            user_id=row.user_id,
            updated_at=row.updated_at,
            message_count=int(row.mc or 0),
            first_user_message=snippet,
            model=row.model,
            provider=row.provider,
            state=json.loads(row.state_json or "{}"),
        )

    @staticmethod
    def _row_to_entry(row: Any) -> SessionStoreEntry:
        return SessionStoreEntry(
            session_id=row.session_id,
            updated_at=row.updated_at,
            model=row.model,
            provider=row.provider,
            prompt_tokens=row.prompt_tokens,
            completion_tokens=row.completion_tokens,
            total_tokens=row.total_tokens,
            compaction_count=row.compaction_count,
            active_skill_ids=json.loads(row.active_skill_ids_json or "[]"),
            state=json.loads(row.state_json or "{}"),
        )

    async def delete(
        self,
        session_id: str,
        user_id: str,
    ) -> bool:
        async with agent_scoped_session(self._sessionmaker, self._agent_id) as s:
            existing = (await s.execute(
                select(SessionMeta.session_id).where(
                    SessionMeta.session_id == session_id,
                    SessionMeta.user_id == user_id,
                )
            )).first()
            if existing is None:
                return False
            await s.execute(
                delete(SessionMessage).where(
                    SessionMessage.session_id == session_id,
                    SessionMessage.user_id == user_id,
                )
            )
            await s.execute(
                delete(SessionMeta).where(
                    SessionMeta.session_id == session_id,
                    SessionMeta.user_id == user_id,
                )
            )
            await s.commit()
        return True

    async def get_raw_transcript(
        self,
        session_id: str,
        user_id: str,
    ) -> str | None:
        async with agent_scoped_session(self._sessionmaker, self._agent_id) as s:
            meta_row = (await s.execute(
                select(SessionMeta.session_id).where(
                    SessionMeta.session_id == session_id,
                    SessionMeta.user_id == user_id,
                )
            )).first()
            if meta_row is None:
                return None
            msg_rows = (await s.execute(
                select(
                    SessionMessage.payload_json,
                    SessionMessage.timestamp,
                )
                .where(
                    SessionMessage.session_id == session_id,
                    SessionMessage.user_id == user_id,
                )
                .order_by(SessionMessage.seq.asc())
            )).all()

        header = SessionHeader(
            id=session_id, timestamp=datetime.now().isoformat(), cwd=os.getcwd(),
        )
        lines = [json.dumps(header.to_dict(), ensure_ascii=False)]
        for payload, ts in msg_rows:
            entry = MessageEntry(
                message=json.loads(payload),
                timestamp=ts,
            )
            lines.append(json.dumps(entry.to_dict(), ensure_ascii=False))
        return "\n".join(lines) + "\n"

    async def put_raw_transcript(
        self,
        session_id: str,
        user_id: str,
        jsonl_content: str,
    ) -> None:
        """Validate JSONL then atomically replace messages in one transaction."""
        parsed = parse_raw_jsonl(session_id, jsonl_content)
        rows: list[dict] = [
            {
                "session_id": session_id,
                "user_id": user_id,
                "seq": i - 2,
                "payload_json": json.dumps(data["message"], ensure_ascii=False),
                "timestamp": int(data.get("timestamp", 0) or 0),
            }
            for (i, data) in parsed
        ]

        async with agent_scoped_session(self._sessionmaker, self._agent_id) as s:
            # User-id ownership guard; the agent filter is automatic.
            owner = (await s.execute(
                select(SessionMeta.session_id).where(
                    SessionMeta.session_id == session_id,
                    SessionMeta.user_id == user_id,
                )
            )).first()
            if owner is None:
                raise RawJsonlValidationError(
                    f"session {session_id!r} not found for user {user_id!r}",
                    line_number=1,
                )
            await s.execute(
                delete(SessionMessage).where(
                    SessionMessage.session_id == session_id,
                )
            )
            if rows:
                await s.execute(sqlite_insert(SessionMessage), rows)
            await s.commit()

    async def finalize(
        self,
        session_id: str,
        user_id: str,
    ) -> None:
        """SQLite/PG: no-op. S3 (PR4): flush in-memory buffer."""
        return None
