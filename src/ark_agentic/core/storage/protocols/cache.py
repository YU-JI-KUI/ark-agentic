"""Cache Protocol — generic KV with optional TTL.

Backed by ``aiocache`` (memory/redis/memcached) via ``CACHE_URL`` env.
The 4-method shape matches ``aiocache.BaseCache``; the adapter in
``core.storage.cache_adapter`` normalises return types so business code
sees plain ``None`` for writes and a typed ``Cache`` Protocol for reads.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Cache(Protocol):
    """Generic KV with optional TTL.

    Multi-worker deployments must use a network backend (Redis / Memcached);
    ``validate_deployment_config()`` enforces this.
    """

    async def get(self, key: str) -> Any | None:
        ...

    async def set(
        self,
        key: str,
        value: Any,
        ttl: float | None = None,
    ) -> None:
        """Fractional seconds allowed (used in tests). Backends with
        integer-only TTL must round up."""
        ...

    async def delete(self, key: str) -> None:
        ...

    async def exists(self, key: str) -> bool:
        ...
