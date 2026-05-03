"""MemoryCache — in-process Cache implementation.

Single-process dict + monotonic clock TTL. Backend-agnostic: not under
``backends/file`` because nothing about it touches the file system. The
multi-worker safeguard lives in ``core.startup_guard``
(``validate_deployment_config``).
"""

from __future__ import annotations

import asyncio
import time
from typing import Any


class MemoryCache:
    """In-process Cache backed by a dict + asyncio.Lock."""

    def __init__(self) -> None:
        self._store: dict[str, tuple[Any, float | None]] = {}
        self._lock = asyncio.Lock()

    def _is_expired(self, expires_at: float | None) -> bool:
        return expires_at is not None and time.monotonic() >= expires_at

    async def get(self, key: str) -> Any | None:
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            value, expires_at = entry
            if self._is_expired(expires_at):
                self._store.pop(key, None)
                return None
            return value

    async def set(
        self,
        key: str,
        value: Any,
        ttl_seconds: float | None = None,
    ) -> None:
        expires_at = (
            time.monotonic() + ttl_seconds if ttl_seconds is not None else None
        )
        async with self._lock:
            self._store[key] = (value, expires_at)

    async def delete(self, key: str) -> None:
        async with self._lock:
            self._store.pop(key, None)

    async def exists(self, key: str) -> bool:
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return False
            _, expires_at = entry
            if self._is_expired(expires_at):
                self._store.pop(key, None)
                return False
            return True
