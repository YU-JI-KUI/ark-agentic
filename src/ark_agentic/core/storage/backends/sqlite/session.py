"""SqliteSessionRepository — SQLAlchemy AsyncEngine implementation.

Schema:
- ``session_meta``: per (session_id) row with model/provider/state/tokens
- ``session_messages``: append-only JSONL payloads keyed by (session_id, seq)

Authorisation note:
- Every method that accepts ``user_id`` enforces it in the WHERE clause so
  that the SQLite backend has the same ownership semantics as the file
  backend (which scopes by ``{sessions_dir}/{user_id}/...``).

PR3 PG TODO:
- ``load_messages(limit=None)`` should raise on PG (forces pagination on hot path).
- ``put_raw_transcript`` already runs DELETE+INSERT in one transaction; PG keeps
  the same shape.
"""

from __future__ import annotations

import json
import os
from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncEngine

from ....db.models import SessionMessage, SessionMeta
from ....persistence import (
    MessageEntry,
    RawJsonlValidationError,
    SessionHeader,
    SessionStoreEntry,
    deserialize_message,
    serialize_message,
)
from ....types import AgentMessage


class SqliteSessionRepository:
    """SessionRepository over a SQLAlchemy AsyncEngine (SQLite/PG)."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

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
        # without the SELECT-then-INSERT race window.
        stmt = sqlite_insert(SessionMeta).values(
            session_id=session_id,
            user_id=user_id,
            updated_at=0,
            model=model,
            provider=provider,
            session_ref=None,
            state_json=json.dumps(state, ensure_ascii=False),
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            compaction_count=0,
            active_skill_ids_json="[]",
        ).on_conflict_do_nothing(index_elements=["session_id"])
        async with self._engine.begin() as conn:
            await conn.execute(stmt)

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
        async with self._engine.begin() as conn:
            next_seq = (await conn.execute(
                select(func.coalesce(func.max(SessionMessage.seq), -1) + 1)
                .where(
                    SessionMessage.session_id == session_id,
                    SessionMessage.user_id == user_id,
                )
            )).scalar_one()
            await conn.execute(
                sqlite_insert(SessionMessage).values(
                    session_id=session_id,
                    user_id=user_id,
                    seq=next_seq,
                    payload_json=payload,
                    timestamp=ts_ms,
                )
            )

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
        async with self._engine.connect() as conn:
            rows = (await conn.execute(stmt)).all()
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
            "session_ref": entry.session_ref,
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
        # see "no row" and race two INSERTs.
        stmt = sqlite_insert(SessionMeta).values(
            session_id=session_id, **values,
        ).on_conflict_do_update(
            index_elements=["session_id"],
            set_=values,
        )
        async with self._engine.begin() as conn:
            await conn.execute(stmt)

    async def load_meta(
        self,
        session_id: str,
        user_id: str,
    ) -> SessionStoreEntry | None:
        async with self._engine.connect() as conn:
            row = (await conn.execute(
                select(SessionMeta).where(
                    SessionMeta.session_id == session_id,
                    SessionMeta.user_id == user_id,
                )
            )).first()
        if row is None:
            return None
        return SessionStoreEntry(
            session_id=row.session_id,
            updated_at=row.updated_at,
            session_ref=row.session_ref,
            model=row.model,
            provider=row.provider,
            prompt_tokens=row.prompt_tokens,
            completion_tokens=row.completion_tokens,
            total_tokens=row.total_tokens,
            compaction_count=row.compaction_count,
            active_skill_ids=json.loads(row.active_skill_ids_json or "[]"),
            state=json.loads(row.state_json or "{}"),
        )

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
        async with self._engine.connect() as conn:
            rows = (await conn.execute(stmt)).all()
        return [r[0] for r in rows]

    async def list_all_sessions(
        self,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[tuple[str, str]]:
        stmt = (
            select(SessionMeta.user_id, SessionMeta.session_id)
            .order_by(SessionMeta.updated_at.desc())
        )
        if limit is not None:
            stmt = stmt.limit(limit).offset(offset)
        async with self._engine.connect() as conn:
            rows = (await conn.execute(stmt)).all()
        return [(r[0], r[1]) for r in rows]

    async def delete(
        self,
        session_id: str,
        user_id: str,
    ) -> bool:
        async with self._engine.begin() as conn:
            existing = (await conn.execute(
                select(SessionMeta.session_id).where(
                    SessionMeta.session_id == session_id,
                    SessionMeta.user_id == user_id,
                )
            )).first()
            if existing is None:
                # Nothing owned by this user — leave any other owner's
                # rows alone.
                return False
            await conn.execute(
                delete(SessionMessage).where(
                    SessionMessage.session_id == session_id,
                    SessionMessage.user_id == user_id,
                )
            )
            await conn.execute(
                delete(SessionMeta).where(
                    SessionMeta.session_id == session_id,
                    SessionMeta.user_id == user_id,
                )
            )
        return True

    async def get_raw_transcript(
        self,
        session_id: str,
        user_id: str,
    ) -> str | None:
        async with self._engine.connect() as conn:
            meta_row = (await conn.execute(
                select(SessionMeta.session_id).where(
                    SessionMeta.session_id == session_id,
                    SessionMeta.user_id == user_id,
                )
            )).first()
            if meta_row is None:
                return None
            msg_rows = (await conn.execute(
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
        lines = [line for line in jsonl_content.splitlines() if line.strip()]
        if not lines:
            raise RawJsonlValidationError("至少需要一行（session header）", line_number=1)
        try:
            first = json.loads(lines[0])
        except json.JSONDecodeError as e:
            raise RawJsonlValidationError(
                f"首行非法 JSON: {e}", line_number=1,
            ) from e
        if first.get("type") != "session":
            raise RawJsonlValidationError("首行 type 必须为 session", line_number=1)
        header_id = (first.get("id") or "").strip()
        if header_id != session_id.strip():
            raise RawJsonlValidationError(
                f"首行 id 与 URL session_id 不一致: {header_id!r} vs {session_id!r}",
                line_number=1,
            )

        rows: list[dict] = []
        for i, line in enumerate(lines[1:], start=2):
            try:
                data = json.loads(line)
            except json.JSONDecodeError as e:
                raise RawJsonlValidationError(
                    f"第 {i} 行非法 JSON: {e}", line_number=i,
                ) from e
            if data.get("type") != "message":
                raise RawJsonlValidationError(
                    f"第 {i} 行 type 必须为 message", line_number=i,
                )
            if "message" not in data or not isinstance(data["message"], dict):
                raise RawJsonlValidationError(
                    f"第 {i} 行必须含 message 对象", line_number=i,
                )
            rows.append({
                "session_id": session_id,
                "user_id": user_id,
                "seq": i - 2,
                "payload_json": json.dumps(data["message"], ensure_ascii=False),
                "timestamp": int(data.get("timestamp", 0) or 0),
            })

        async with self._engine.begin() as conn:
            # Confirm ownership before any mutation so a misrouted call
            # cannot wipe or replace another owner's transcript.
            owner = (await conn.execute(
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
            await conn.execute(
                delete(SessionMessage).where(
                    SessionMessage.session_id == session_id,
                )
            )
            if rows:
                # Single executemany round-trip instead of N INSERTs.
                await conn.execute(sqlite_insert(SessionMessage), rows)

    async def finalize(
        self,
        session_id: str,
        user_id: str,
    ) -> None:
        """SQLite/PG: no-op. S3 (PR4): flush in-memory buffer."""
        return None
