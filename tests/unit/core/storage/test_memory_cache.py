"""MemoryCache behavior tests."""

from __future__ import annotations

import asyncio

import pytest

from ark_agentic.core.storage.backends.file.memory_cache import MemoryCache
from ark_agentic.core.storage.protocols import Cache


@pytest.fixture
def cache() -> MemoryCache:
    return MemoryCache()


async def test_implements_cache_protocol(cache: MemoryCache):
    assert isinstance(cache, Cache)


async def test_get_returns_none_when_missing(cache: MemoryCache):
    result = await cache.get("absent")

    assert result is None


async def test_set_then_get_round_trip(cache: MemoryCache):
    await cache.set("k", {"a": 1})

    assert await cache.get("k") == {"a": 1}


async def test_ttl_expires_value(cache: MemoryCache):
    await cache.set("k", "v", ttl_seconds=0.1)

    await asyncio.sleep(0.25)
    assert await cache.get("k") is None


async def test_delete_removes_key(cache: MemoryCache):
    await cache.set("k", "v")

    await cache.delete("k")

    assert await cache.get("k") is None


async def test_exists_only_for_active_keys(cache: MemoryCache):
    await cache.set("k", "v")
    assert await cache.exists("k") is True

    await cache.set("expired", "v", ttl_seconds=0.05)
    await asyncio.sleep(0.15)
    assert await cache.exists("expired") is False


async def test_concurrent_writes_do_not_corrupt(cache: MemoryCache):
    async def writer(i: int) -> None:
        await cache.set(f"k{i}", i)

    await asyncio.gather(*[writer(i) for i in range(50)])

    for i in range(50):
        assert await cache.get(f"k{i}") == i
