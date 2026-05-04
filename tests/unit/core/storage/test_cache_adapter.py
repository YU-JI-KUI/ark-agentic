"""Tests for the aiocache-backed Cache adapter."""

from __future__ import annotations

import asyncio

import pytest

from ark_agentic.core.storage.cache_adapter import (
    get_cache,
    reset_cache_for_testing,
    set_cache_for_testing,
)
from ark_agentic.core.storage.protocols import Cache


@pytest.fixture(autouse=True)
def _reset_cache():
    reset_cache_for_testing()
    yield
    reset_cache_for_testing()


def test_get_cache_returns_protocol(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("CACHE_URL", raising=False)
    cache = get_cache()
    assert isinstance(cache, Cache)


def test_get_cache_is_singleton(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("CACHE_URL", raising=False)
    assert get_cache() is get_cache()


async def test_set_then_get_round_trip(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("CACHE_URL", raising=False)
    cache = get_cache()

    await cache.set("k", {"a": 1})

    assert await cache.get("k") == {"a": 1}


async def test_get_returns_none_when_missing(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("CACHE_URL", raising=False)
    cache = get_cache()

    assert await cache.get("absent") is None


async def test_ttl_expires_value(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("CACHE_URL", raising=False)
    cache = get_cache()

    await cache.set("k", "v", ttl=1)
    assert await cache.get("k") == "v"

    # aiocache memory backend uses integer TTL with second granularity;
    # sleep slightly past the TTL boundary to avoid flakiness.
    await asyncio.sleep(1.2)
    assert await cache.get("k") is None


async def test_delete_removes_key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("CACHE_URL", raising=False)
    cache = get_cache()

    await cache.set("k", "v")
    await cache.delete("k")

    assert await cache.get("k") is None
    assert await cache.exists("k") is False


async def test_set_cache_for_testing_overrides_singleton():
    class _Stub:
        async def get(self, key): return "stub"
        async def set(self, key, value, ttl=None): return None
        async def delete(self, key): return None
        async def exists(self, key): return True

    set_cache_for_testing(_Stub())
    cache = get_cache()
    assert await cache.get("anything") == "stub"
