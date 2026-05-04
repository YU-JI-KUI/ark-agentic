"""``CachedMemoryRepository`` — caches per-user memory reads.

Wraps any ``MemoryRepository`` (file / sqlite / future PG) and adds:

- ``read(user_id)``                  → cache hit avoids file/DB I/O on
  every chat turn that consults user memory.
- ``upsert_headings`` / ``overwrite``→ invalidate the matching ``mem:{uid}``
  key so the next read sees the fresh content.

What is NOT cached (and why):

- ``list_users`` — paged, mutates whenever any user gets memory; the
  proactive scanner (the only frequent caller) iterates all users once
  per day so the value of caching is marginal.

The ``inner`` property is intentionally public so factories / tests can
peek through the wrapper at the underlying backend.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..protocols import Cache, MemoryRepository


_DEFAULT_TTL_SECONDS = 300


class CachedMemoryRepository:
    """Decorator that adds per-user-memory caching to a ``MemoryRepository``."""

    NAMESPACE = "mem"

    def __init__(
        self,
        inner: "MemoryRepository",
        cache: "Cache",
        ttl: int = _DEFAULT_TTL_SECONDS,
    ) -> None:
        self._inner = inner
        self._cache = cache
        self._ttl = ttl

    @property
    def inner(self) -> "MemoryRepository":
        """The wrapped repository — exposed for factories and tests."""
        return self._inner

    def _key(self, user_id: str) -> str:
        return f"{self.NAMESPACE}:{user_id}"

    # ── Cached read ─────────────────────────────────────────────

    async def read(self, user_id: str) -> str:
        key = self._key(user_id)
        cached = await self._cache.get(key)
        if cached is not None:
            return cached
        content = await self._inner.read(user_id)
        # Cache empty strings too (a "no memory" state is itself useful
        # to remember; otherwise every miss re-reads).
        await self._cache.set(key, content, ttl=self._ttl)
        return content

    # ── Invalidating writes ─────────────────────────────────────

    async def upsert_headings(
        self,
        user_id: str,
        content: str,
    ) -> tuple[list[str], list[str]]:
        result = await self._inner.upsert_headings(user_id, content)
        await self._cache.delete(self._key(user_id))
        return result

    async def overwrite(self, user_id: str, content: str) -> None:
        await self._inner.overwrite(user_id, content)
        await self._cache.delete(self._key(user_id))

    # ── Pass-through ────────────────────────────────────────────

    async def list_users(
        self,
        limit: int | None = None,
        offset: int = 0,
        order_by_updated_desc: bool = True,
    ) -> list[str]:
        return await self._inner.list_users(
            limit=limit,
            offset=offset,
            order_by_updated_desc=order_by_updated_desc,
        )
