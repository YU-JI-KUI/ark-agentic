"""
Tests for core/registry.py — AgentRegistry

Covers: register, get, list_ids, and KeyError on missing agent.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from ark_agentic.core.agent.registry import AgentRegistry
from ark_agentic.core.agent.runner import AgentRunner


@pytest.fixture
def registry() -> AgentRegistry:
    return AgentRegistry()


@pytest.fixture
def mock_runner() -> AgentRunner:
    return MagicMock(spec=AgentRunner)


class TestAgentRegistry:
    """Unit tests for AgentRegistry."""

    def test_register_and_get(self, registry: AgentRegistry, mock_runner: AgentRunner):
        """P0: Register an agent, then retrieve it by ID."""
        # Arrange & Act
        registry.register("test-agent", mock_runner)

        # Assert
        result = registry.get("test-agent")
        assert result is mock_runner, "get() should return the exact same runner instance"

    def test_get_nonexistent_raises_key_error(self, registry: AgentRegistry):
        """P0: get() on a missing ID should raise KeyError."""
        with pytest.raises(KeyError, match="nonexistent"):
            registry.get("nonexistent")

    def test_list_ids_empty(self, registry: AgentRegistry):
        """P1: list_ids() on empty registry should return empty list."""
        assert registry.list_ids() == []

    def test_list_ids_after_registrations(self, registry: AgentRegistry, mock_runner: AgentRunner):
        """P0: list_ids() should return all registered agent IDs."""
        registry.register("alpha", mock_runner)
        registry.register("beta", mock_runner)

        ids = registry.list_ids()
        assert set(ids) == {"alpha", "beta"}, f"Expected {{'alpha', 'beta'}}, got {set(ids)}"

    def test_register_overwrites_existing(self, registry: AgentRegistry):
        """P1: Registering the same ID twice should silently overwrite."""
        runner_v1 = MagicMock(spec=AgentRunner)
        runner_v2 = MagicMock(spec=AgentRunner)

        registry.register("same-id", runner_v1)
        registry.register("same-id", runner_v2)

        result = registry.get("same-id")
        assert result is runner_v2, "Second registration should overwrite the first"
