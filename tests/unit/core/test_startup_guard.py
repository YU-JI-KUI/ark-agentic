"""Tests for startup guard validation."""

from __future__ import annotations

import pytest

from ark_agentic.core.startup_guard import (
    DeploymentConfigError,
    validate_deployment_config,
)


def test_default_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CACHE_URL", raising=False)
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)

    validate_deployment_config()


def test_memory_url_with_single_worker_passes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CACHE_URL", "memory://")
    monkeypatch.setenv("WEB_CONCURRENCY", "1")

    validate_deployment_config()


def test_memory_url_with_multi_worker_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CACHE_URL", "memory://")
    monkeypatch.setenv("WEB_CONCURRENCY", "4")

    with pytest.raises(DeploymentConfigError) as exc_info:
        validate_deployment_config()

    assert "4" in str(exc_info.value)
    assert "memory" in str(exc_info.value).lower()


def test_redis_url_with_multi_worker_passes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CACHE_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("WEB_CONCURRENCY", "4")

    validate_deployment_config()


def test_memcached_url_with_many_workers_passes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CACHE_URL", "memcached://localhost:11211")
    monkeypatch.setenv("WEB_CONCURRENCY", "8")

    validate_deployment_config()


def test_invalid_workers_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WEB_CONCURRENCY", "not-a-number")

    with pytest.raises(DeploymentConfigError, match="must be an integer"):
        validate_deployment_config()
