"""FileSessionRepository — file-backed SessionRepository.

Owns all file I/O for session storage:
- ``{sessions_dir}/{user_id}/{session_id}.jsonl``  — JSONL transcript
- ``{sessions_dir}/{user_id}/sessions.json``       — per-user meta map

JSONL serialisation primitives (``SessionHeader``, ``MessageEntry``,
``serialize_message``, ``deserialize_message``, ``RawJsonlValidationError``)
live in ``core.session.format`` because the SQLite backend's
``put_raw_transcript`` / ``get_raw_transcript`` reuse them — they are
JSONL utilities, not file-backend internals. ``FileLock`` is local to
this backend (``._lock``).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path

from ...session.format import (
    MessageEntry,
    SessionHeader,
    deserialize_message,
    parse_raw_jsonl,
    serialize_message,
)
from ._lock import FileLock
from ._paginate import paginate
from ...types import AgentMessage
from ..entries import SessionStoreEntry, SessionSummaryEntry

logger = logging.getLogger(__name__)

_META_FILENAME = "sessions.json"
_META_LOCK_FILENAME = "sessions.json.lock"
_META_CACHE_TTL_SECONDS = 45.0


def _first_text_snippet(message: dict) -> str | None:
    """Return the 80-char snippet of the first ``text`` block in ``content``.

    ``serialize_message`` writes ``content`` as a list of typed blocks
    (``[{"type": "text", "text": ...}, ...]``); legacy rows stored a plain
    string. Both shapes are handled.
    """
    content = message.get("content")
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


class FileSessionRepository:
    """File-backed implementation of SessionRepository."""

    def __init__(self, sessions_dir: str | Path) -> None:
        self._sessions_dir = Path(sessions_dir)
        self._sessions_dir.mkdir(parents=True, exist_ok=True)

        # Per-user meta cache (sessions.json contents) keyed by user_id.
        self._meta_cache: dict[str, dict[str, SessionStoreEntry]] = {}
        self._meta_cache_at: dict[str, float] = {}

    # ── Path helpers ────────────────────────────────────────────────

    def _user_dir(self, user_id: str) -> Path:
        return self._sessions_dir / user_id

    def _transcript_path(self, session_id: str, user_id: str) -> Path:
        return self._user_dir(user_id) / f"{session_id}.jsonl"

    def _transcript_lock(self, session_id: str, user_id: str) -> Path:
        return self._user_dir(user_id) / f"{session_id}.jsonl.lock"

    def _meta_path(self, user_id: str) -> Path:
        return self._user_dir(user_id) / _META_FILENAME

    def _meta_lock(self, user_id: str) -> Path:
        return self._user_dir(user_id) / _META_LOCK_FILENAME

    # ── Protocol: lifecycle ─────────────────────────────────────────

    async def create(
        self,
        session_id: str,
        user_id: str,
        model: str,
        provider: str,
        state: dict,
    ) -> None:
        await self._ensure_transcript_header(session_id, user_id)
        entry = SessionStoreEntry(
            session_id=session_id,
            updated_at=0,
            model=model,
            provider=provider,
            state=state,
        )
        await self._meta_upsert(user_id, session_id, entry)

    async def delete(self, session_id: str, user_id: str) -> bool:
        deleted = await asyncio.to_thread(
            self._delete_transcript_sync, session_id, user_id,
        )
        await self._meta_delete(user_id, session_id)
        return deleted

    async def finalize(self, session_id: str, user_id: str) -> None:
        """File backend: no-op. S3 (future) flushes its in-memory buffer."""
        return None

    # ── Protocol: messages ──────────────────────────────────────────

    async def append_message(
        self,
        session_id: str,
        user_id: str,
        message: AgentMessage,
    ) -> None:
        await self._ensure_transcript_header(session_id, user_id)
        entry = MessageEntry(
            message=serialize_message(message),
            timestamp=int(message.timestamp.timestamp() * 1000),
        )
        async with FileLock(self._transcript_lock(session_id, user_id)):
            path = self._transcript_path(session_id, user_id)
            self._ensure_trailing_newline(path)
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")

    async def load_messages(
        self,
        session_id: str,
        user_id: str,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[AgentMessage]:
        messages = await asyncio.to_thread(
            self._load_messages_sync, session_id, user_id,
        )
        return paginate(messages, limit, offset)

    async def get_raw_transcript(
        self,
        session_id: str,
        user_id: str,
    ) -> str | None:
        return await asyncio.to_thread(
            self._read_raw_sync, session_id, user_id,
        )

    async def put_raw_transcript(
        self,
        session_id: str,
        user_id: str,
        jsonl_content: str,
    ) -> None:
        """Validate JSONL then atomically replace the transcript on disk.

        Validation errors (``RawJsonlValidationError``) are raised before
        any write happens.
        """
        parse_raw_jsonl(session_id, jsonl_content)
        path = self._transcript_path(session_id, user_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = (
            jsonl_content if jsonl_content.endswith("\n")
            else jsonl_content + "\n"
        )
        async with FileLock(self._transcript_lock(session_id, user_id)):
            path.write_text(payload, encoding="utf-8")

    # ── Protocol: meta ──────────────────────────────────────────────

    async def update_meta(
        self,
        session_id: str,
        user_id: str,
        entry: SessionStoreEntry,
    ) -> None:
        await self._meta_upsert(user_id, session_id, entry)

    async def load_meta(
        self,
        session_id: str,
        user_id: str,
    ) -> SessionStoreEntry | None:
        return await asyncio.to_thread(
            self._load_meta_sync, user_id, session_id,
        )

    async def list_session_ids(
        self,
        user_id: str,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[str]:
        ids = await asyncio.to_thread(self._list_session_ids_sync, user_id)
        return paginate(ids, limit, offset)

    async def list_session_metas(
        self,
        user_id: str,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[SessionStoreEntry]:
        store = await asyncio.to_thread(self._load_meta_store, user_id, False)
        ordered = sorted(
            store.values(), key=lambda e: e.updated_at, reverse=True,
        )
        return paginate(ordered, limit, offset)

    async def list_all_sessions(
        self,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[tuple[str, str]]:
        rows = await asyncio.to_thread(self._list_all_sessions_sync)
        return paginate(rows, limit, offset)

    async def list_session_summaries(
        self,
        user_id: str,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[SessionSummaryEntry]:
        store = await asyncio.to_thread(self._load_meta_store, user_id, False)
        ordered = sorted(
            store.values(), key=lambda e: e.updated_at, reverse=True,
        )
        page = paginate(ordered, limit, offset)
        return [
            await asyncio.to_thread(
                self._summarize_session_sync, user_id, entry,
            )
            for entry in page
        ]

    async def list_all_session_summaries(
        self,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[SessionSummaryEntry]:
        rows = await asyncio.to_thread(self._collect_all_summary_metas)
        page = paginate(rows, limit, offset)
        return [
            await asyncio.to_thread(
                self._summarize_session_sync, uid, entry,
            )
            for uid, entry in page
        ]

    def _collect_all_summary_metas(
        self,
    ) -> list[tuple[str, SessionStoreEntry]]:
        if not self._sessions_dir.exists():
            return []
        rows: list[tuple[str, SessionStoreEntry]] = []
        for user_dir in self._sessions_dir.iterdir():
            if not user_dir.is_dir():
                continue
            store = self._load_meta_store(user_dir.name, skip_cache=False)
            for entry in store.values():
                rows.append((user_dir.name, entry))
        rows.sort(key=lambda t: t[1].updated_at, reverse=True)
        return rows

    def _summarize_session_sync(
        self, user_id: str, entry: SessionStoreEntry,
    ) -> SessionSummaryEntry:
        """Walk the JSONL once: count message lines + grab first user content.

        Avoids the full ``deserialize_message`` pipeline for every line.
        Stops parsing message bodies as soon as the first user content is
        found; subsequent lines are only counted via cheap JSON load +
        type check.
        """
        path = self._transcript_path(entry.session_id, user_id)
        message_count = 0
        snippet: str | None = None
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if data.get("type") != "message":
                            continue
                        message_count += 1
                        if snippet is None:
                            msg = data.get("message") or {}
                            if msg.get("role") == "user":
                                snippet = _first_text_snippet(msg)
            except OSError as e:
                logger.warning(
                    "summary scan failed for %s: %s", path, e,
                )
        return SessionSummaryEntry(
            session_id=entry.session_id,
            user_id=user_id,
            updated_at=entry.updated_at,
            message_count=message_count,
            first_user_message=snippet,
            model=entry.model,
            provider=entry.provider,
            state=entry.state,
        )

    # ── Sync helpers (run via asyncio.to_thread) ────────────────────

    @staticmethod
    def _ensure_trailing_newline(filepath: Path) -> None:
        """Guard against torn-tail JSONL: ensure file ends with newline."""
        if filepath.exists() and filepath.stat().st_size > 0:
            with open(filepath, "rb") as rf:
                rf.seek(-1, 2)
                if rf.read(1) != b"\n":
                    with open(filepath, "a", encoding="utf-8") as f:
                        f.write("\n")

    async def _ensure_transcript_header(
        self, session_id: str, user_id: str,
    ) -> None:
        path = self._transcript_path(session_id, user_id)
        if path.exists():
            return

        header = SessionHeader(
            id=session_id,
            timestamp=datetime.now().isoformat(),
            cwd=os.getcwd(),
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        async with FileLock(self._transcript_lock(session_id, user_id)):
            with open(path, "w", encoding="utf-8") as f:
                f.write(
                    json.dumps(header.to_dict(), ensure_ascii=False) + "\n"
                )

    def _load_messages_sync(
        self, session_id: str, user_id: str,
    ) -> list[AgentMessage]:
        path = self._transcript_path(session_id, user_id)
        if not path.exists():
            return []

        messages: list[AgentMessage] = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    if data.get("type") == "message":
                        messages.append(
                            deserialize_message(data.get("message", {}))
                        )
                except json.JSONDecodeError:
                    logger.warning("skipping invalid JSON line: %.50s", line)
        return messages

    def _read_raw_sync(self, session_id: str, user_id: str) -> str | None:
        path = self._transcript_path(session_id, user_id)
        return path.read_text(encoding="utf-8") if path.exists() else None

    def _delete_transcript_sync(
        self, session_id: str, user_id: str,
    ) -> bool:
        path = self._transcript_path(session_id, user_id)
        lock_path = self._transcript_lock(session_id, user_id)
        deleted = False
        if path.exists():
            path.unlink()
            deleted = True
        if lock_path.exists():
            lock_path.unlink()
        return deleted

    def _list_session_ids_sync(self, user_id: str) -> list[str]:
        user_dir = self._user_dir(user_id)
        if not user_dir.exists():
            return []
        return [
            f.stem for f in user_dir.glob("*.jsonl") if not f.stem.endswith(".lock")
        ]

    def _list_all_sessions_sync(self) -> list[tuple[str, str]]:
        results: list[tuple[str, str]] = []
        if not self._sessions_dir.exists():
            return results
        for user_dir in self._sessions_dir.iterdir():
            if not user_dir.is_dir():
                continue
            for f in user_dir.glob("*.jsonl"):
                if not f.stem.endswith(".lock"):
                    results.append((user_dir.name, f.stem))
        return results

    # ── Meta store (per-user sessions.json with TTL cache) ──────────

    def _load_meta_store(
        self, user_id: str, skip_cache: bool,
    ) -> dict[str, SessionStoreEntry]:
        if not skip_cache:
            cached_at = self._meta_cache_at.get(user_id, 0.0)
            if user_id in self._meta_cache and (
                time.time() - cached_at <= _META_CACHE_TTL_SECONDS
            ):
                return dict(self._meta_cache[user_id])

        store: dict[str, SessionStoreEntry] = {}
        path = self._meta_path(user_id)
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                for key, entry_data in raw.items():
                    store[key] = SessionStoreEntry.from_dict(entry_data)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("failed to load meta store: %s", e)

        self._meta_cache[user_id] = dict(store)
        self._meta_cache_at[user_id] = time.time()
        return store

    def _invalidate_meta_cache(self, user_id: str) -> None:
        self._meta_cache.pop(user_id, None)
        self._meta_cache_at.pop(user_id, None)

    def _load_meta_sync(
        self, user_id: str, session_id: str,
    ) -> SessionStoreEntry | None:
        return self._load_meta_store(user_id, skip_cache=False).get(session_id)

    async def _meta_upsert(
        self,
        user_id: str,
        session_id: str,
        entry: SessionStoreEntry,
    ) -> None:
        path = self._meta_path(user_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        async with FileLock(self._meta_lock(user_id)):
            store = self._load_meta_store(user_id, skip_cache=True)
            store[session_id] = entry
            self._invalidate_meta_cache(user_id)
            self._write_meta_store_sync(path, store)

    async def _meta_delete(self, user_id: str, session_id: str) -> bool:
        async with FileLock(self._meta_lock(user_id)):
            store = self._load_meta_store(user_id, skip_cache=True)
            if session_id not in store:
                return False
            del store[session_id]
            self._invalidate_meta_cache(user_id)
            self._write_meta_store_sync(self._meta_path(user_id), store)
            return True

    @staticmethod
    def _write_meta_store_sync(
        path: Path,
        store: dict[str, SessionStoreEntry],
    ) -> None:
        data = {key: e.to_dict() for key, e in store.items()}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
