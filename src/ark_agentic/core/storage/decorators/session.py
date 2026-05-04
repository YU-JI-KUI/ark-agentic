"""``CachedSessionRepository`` — caches per-session metadata reads.

Wraps any ``SessionRepository`` (file / sqlite / future PG) and adds:

- ``load_meta(sid, uid)``  → cache hit avoids a DB round-trip per chat turn.
- ``update_meta`` / ``delete`` / ``put_raw_transcript`` → invalidate the
  matching ``sess_meta:{uid}:{sid}`` key.

What is NOT cached (and why):

- ``load_messages`` — large variable-size payload, mutated by every
  ``append_message``; would need per-message invalidation.
- ``list_session_ids`` / ``list_session_metas`` / ``list_all_sessions``
  — paged; invalidation across (limit, offset) combos is messy.
  Rarely re-paged in tight loops; can be added later with a per-user
  version-counter pattern if a hot path appears.

The ``inner`` property is intentionally public so factories / tests can
peek through the wrapper at the underlying backend.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...persistence import SessionStoreEntry
    from ...types import AgentMessage
    from ..protocols import Cache, SessionRepository


_DEFAULT_TTL_SECONDS = 60


class CachedSessionRepository:
    """Decorator that adds session-meta caching to a ``SessionRepository``."""

    NAMESPACE = "sess_meta"

    def __init__(
        self,
        inner: "SessionRepository",
        cache: "Cache",
        ttl: int = _DEFAULT_TTL_SECONDS,
    ) -> None:
        self._inner = inner
        self._cache = cache
        self._ttl = ttl

    @property
    def inner(self) -> "SessionRepository":
        """The wrapped repository — exposed for factories and tests."""
        return self._inner

    def _meta_key(self, user_id: str, session_id: str) -> str:
        return f"{self.NAMESPACE}:{user_id}:{session_id}"

    # ── Cached read ─────────────────────────────────────────────

    async def load_meta(
        self,
        session_id: str,
        user_id: str,
    ) -> "SessionStoreEntry | None":
        key = self._meta_key(user_id, session_id)
        cached = await self._cache.get(key)
        if cached is not None:
            return cached
        entry = await self._inner.load_meta(session_id, user_id)
        if entry is not None:
            await self._cache.set(key, entry, ttl=self._ttl)
        return entry

    # ── Invalidating writes ─────────────────────────────────────

    async def update_meta(
        self,
        session_id: str,
        user_id: str,
        entry: "SessionStoreEntry",
    ) -> None:
        await self._inner.update_meta(session_id, user_id, entry)
        await self._cache.delete(self._meta_key(user_id, session_id))

    async def delete(self, session_id: str, user_id: str) -> bool:
        result = await self._inner.delete(session_id, user_id)
        await self._cache.delete(self._meta_key(user_id, session_id))
        return result

    async def put_raw_transcript(
        self,
        session_id: str,
        user_id: str,
        jsonl_content: str,
    ) -> None:
        await self._inner.put_raw_transcript(session_id, user_id, jsonl_content)
        # put_raw rebuilds the transcript wholesale — meta token counts /
        # state may diverge from what we cached.
        await self._cache.delete(self._meta_key(user_id, session_id))

    # ── Pass-through ────────────────────────────────────────────

    async def create(
        self,
        session_id: str,
        user_id: str,
        model: str,
        provider: str,
        state: dict,
    ) -> None:
        await self._inner.create(session_id, user_id, model, provider, state)

    async def append_message(
        self,
        session_id: str,
        user_id: str,
        message: "AgentMessage",
    ) -> None:
        await self._inner.append_message(session_id, user_id, message)

    async def load_messages(
        self,
        session_id: str,
        user_id: str,
        limit: int | None = None,
        offset: int = 0,
    ) -> "list[AgentMessage]":
        return await self._inner.load_messages(session_id, user_id, limit, offset)

    async def list_session_ids(
        self,
        user_id: str,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[str]:
        return await self._inner.list_session_ids(user_id, limit, offset)

    async def list_session_metas(
        self,
        user_id: str,
        limit: int | None = None,
        offset: int = 0,
    ) -> "list[SessionStoreEntry]":
        return await self._inner.list_session_metas(user_id, limit, offset)

    async def list_all_sessions(
        self,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[tuple[str, str]]:
        return await self._inner.list_all_sessions(limit, offset)

    async def get_raw_transcript(
        self,
        session_id: str,
        user_id: str,
    ) -> str | None:
        return await self._inner.get_raw_transcript(session_id, user_id)

    async def finalize(self, session_id: str, user_id: str) -> None:
        await self._inner.finalize(session_id, user_id)
