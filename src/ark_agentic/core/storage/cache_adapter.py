"""Cache backed by aiocache — Memory / Redis / Memcached via env URL.

Business code sees only the ``Cache`` Protocol; the ``aiocache`` import
is isolated to this module so a future library swap is one file's work.

Backend is selected by ``CACHE_URL`` env:

  - ``memory://`` (default) → in-process dict
  - ``redis://host:port/db`` → Redis
  - ``memcached://host:port`` → Memcached

``validate_deployment_config`` rejects ``memory://`` + multi-worker.
"""

from __future__ import annotations

import os
from typing import Any

from aiocache import Cache as _AioCache
from aiocache.base import BaseCache

from .protocols import Cache


class _AioCacheAdapter:
    """Adapt ``aiocache.BaseCache`` to our 4-method ``Cache`` Protocol.

    Adapter responsibilities:
    1. Normalise the return types (aiocache's set/delete return int/bool;
       our Protocol returns None).
    2. Keep the ``aiocache`` import out of business code.
    """

    def __init__(self, backend: BaseCache) -> None:
        self._backend = backend

    async def get(self, key: str) -> Any | None:
        return await self._backend.get(key, default=None)

    async def set(
        self, key: str, value: Any, ttl: float | None = None,
    ) -> None:
        await self._backend.set(key, value, ttl=ttl)

    async def delete(self, key: str) -> None:
        await self._backend.delete(key)

    async def exists(self, key: str) -> bool:
        return await self._backend.exists(key)


# ── Process-wide singleton ────────────────────────────────────────


_cache: Cache | None = None
_test_cache: Cache | None = None


def get_cache() -> Cache:
    """Return the process-wide cache resolved from ``CACHE_URL``.

    Default ``memory://``; production multi-worker should use ``redis://``.
    Tests can swap via ``set_cache_for_testing``.
    """
    global _cache
    if _test_cache is not None:
        return _test_cache
    if _cache is None:
        url = os.getenv("CACHE_URL", "memory://")
        _cache = _AioCacheAdapter(_AioCache.from_url(url))
    return _cache


def set_cache_for_testing(cache: Cache) -> None:
    """Inject a per-test cache; ``get_cache()`` returns it until reset."""
    global _test_cache
    _test_cache = cache


def reset_cache_for_testing() -> None:
    """Drop the per-test cache + clear the process singleton."""
    global _cache, _test_cache
    _cache = None
    _test_cache = None
