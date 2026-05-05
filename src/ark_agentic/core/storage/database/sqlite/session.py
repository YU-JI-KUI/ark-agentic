"""SqliteSessionRepository — SQLAlchemy AsyncEngine implementation.

Schema:
- ``session_meta``: per (session_id) row with model/provider/state/tokens
- ``session_messages``: append-only JSONL payloads keyed by (session_id, seq)

Agent isolation:
- The repository is bound to a single ``agent_id`` at construction. All
  ORM SELECT/UPDATE/DELETE statements run inside ``agent_scoped_session``
  which auto-injects ``WHERE agent_id = :bound`` via
  ``with_loader_criteria``. INSERTs read the same value from the
  contextvar so they too land under the bound agent without each call
  site spelling it out.
- ``user_id`` ownership is still enforced explicitly because the
  per-agent invariant is not the same as the per-user one — the file
  backend has identical semantics.

PR3 PG TODO:
- ``load_messages(limit=None)`` should raise on PG (forces pagination on hot path).
- ``put_raw_transcript`` already runs DELETE+INSERT in one transaction; PG keeps
  the same shape.
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
        # ON CONFLICT DO NOTHING gives "create if missing" in one round-trip
        # without the SELECT-then-INSERT race window. ``agent_id`` is
        # populated by the column default reading the contextvar; the PK
        # is composite ``(agent_id, session_id)`` so the conflict target
        # has to mention both columns.
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
        """Append a message with the next sequence number.

        Caller contract: appends to the **same** session_id MUST be serialised
        by the caller (the runner serialises per-session). Concurrent appends
        to the same session can both observe the same MAX(seq) before either
        commits, and the unique ``(session_id, seq)`` index will then reject
        the second insert with ``IntegrityError``. The runner's per-session
        ordering makes this latent today, but a future caller that drops
        that invariant must add retry-on-IntegrityError here.
        """
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
        """SQLite tolerates ``limit=None`` (returns full session); PR3 PG must raise.

        Both are valid in PR2 because SQLite is a single-process embedded DB and
        full-session reads are still cheap. PG hot-path callers must paginate.
        """
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
        # Single-statement upsert. Concurrent callers can no longer both
        # see "no row" and race two INSERTs. The composite PK on
        # ``(agent_id, session_id)`` means cross-agent session_id
        # collisions stay separate rows; without it, this set_ would
        # silently rewrite another agent's metadata.
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
        """List ``(user_id, session_id)`` for every user under THIS agent.

        After agent isolation this no longer crosses agents — the
        ``with_loader_criteria`` filter restricts the scan to the bound
        agent, which matches the file backend's per-agent semantics.
        """
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
        """Per-agent (and optionally per-user) summary scan.

        ``user_id=None`` returns every user's sessions under THIS agent.
        Cross-agent dashboards fan out across the registry — the
        repository never sees data outside its bound agent.
        """
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
        """Single-statement correlated scalar subqueries.

        ``mc`` counts messages per session; ``fum`` returns the
        ``payload_json`` of the earliest user-role message. Pulling the
        whole payload (vs ``json_extract($.content)``) keeps the typing
        story simple — Python truncates the content to 80 chars.

        The correlated subqueries reference ``SessionMessage`` and so
        also receive the ``with_loader_criteria`` agent filter.

        PR3 PG TODO: ``json_extract(... , '$.role')`` is the SQLite
        spelling of the JSON path operator. PostgreSQL needs
        ``payload_json::jsonb ->> 'role'`` (or ``json_extract_path_text``)
        instead — switch via dialect detection on ``self._engine.dialect``
        when the PG backend lands.
        """
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
                # Nothing owned by this user under this agent — leave any
                # other owner's rows alone.
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
            # Confirm ownership before any mutation so a misrouted call
            # cannot wipe or replace another owner's transcript. The agent
            # filter is automatic; this just guards user_id ownership.
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
                # Single executemany round-trip instead of N INSERTs.
                await s.execute(sqlite_insert(SessionMessage), rows)
            await s.commit()

    async def finalize(
        self,
        session_id: str,
        user_id: str,
    ) -> None:
        """SQLite/PG: no-op. S3 (PR4): flush in-memory buffer."""
        return None
