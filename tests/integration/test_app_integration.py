"""Integration tests for API and RunOptions."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from ark_agentic.app import app
from ark_agentic.core.agent.runner import AgentRunner, RunResult
from ark_agentic.core.types import AgentMessage, MessageRole


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)

@pytest.fixture(autouse=True)
def init_agent_registry():
    from ark_agentic.plugins.api import deps
    from ark_agentic.core.agent.registry import AgentRegistry
    # 初始化一个临时的空的 registry
    deps.init_registry(AgentRegistry())
    yield
    # 清理（如果需要，或者允许其保持原样）

@pytest.fixture
def mock_agent_runner():
    """Mock the insurance agent runner."""
    from ark_agentic.core.types import SessionEntry
    with patch("ark_agentic.plugins.api.chat.get_agent") as mock_get:
        runner = AsyncMock(spec=AgentRunner)
        # Mock session manager with proper SessionEntry
        runner.session_manager = MagicMock()
        mock_session = SessionEntry(session_id="test-session", model="mock", provider="mock", state={}, active_skill_ids=[], messages=[])
        
        async def mock_create_session(user_id, *args, **kwargs):
            return mock_session
            
        async def mock_load_session(session_id, user_id, *args, **kwargs):
            return mock_session

        runner.session_manager.create_session = mock_create_session
        runner.session_manager.load_session = mock_load_session
        runner.session_manager.get_session.return_value = mock_session
        
        # Mock run result
        runner.run.return_value = RunResult(
            response=AgentMessage(role=MessageRole.ASSISTANT, content="Hello"),
            turns=1,
            prompt_tokens=10,
            completion_tokens=10
        )
        
        mock_get.return_value = runner
        yield runner

class TestChatRunOptionsIntegration:
    """Test Chat API integration with RunOptions."""

    def test_run_options_valid(self, client: TestClient, mock_agent_runner: AsyncMock):
        """Test valid run_options passed to API."""
        payload = {
            "message": "hello",
            "user_id": "test_user",
            "run_options": {
                "model": "override-model",
                "temperature": 0.1
            }
        }
        
        response = client.post("/chat", json=payload)
        assert response.status_code == 200
        
        # Verify runner called with correct RunOptions
        call_args = mock_agent_runner.run.call_args
        assert call_args is not None
        _, kwargs = call_args
        run_opts = kwargs["run_options"]
        assert run_opts.model == "override-model"
        assert run_opts.temperature == 0.1

    def test_run_options_partial(self, client: TestClient, mock_agent_runner: AsyncMock):
        """Test partial run_options (only model)."""
        payload = {
            "message": "hello",
            "user_id": "test_user",
            "run_options": {
                "model": "override-model"
            }
        }
        
        response = client.post("/chat", json=payload)
        assert response.status_code == 200
        
        call_args = mock_agent_runner.run.call_args
        _, kwargs = call_args
        run_opts = kwargs["run_options"]
        assert run_opts.model == "override-model"
        assert run_opts.temperature is None

    def test_run_options_invalid_temperature(self, client: TestClient):
        """Test validation error for invalid temperature."""
        payload = {
            "message": "hello",
            "user_id": "test_user",
            "run_options": {
                "temperature": 2.5  # Invalid > 2.0
            }
        }
        
        response = client.post("/chat", json=payload)
        assert response.status_code == 422  # Unprocessable Entity
        
        # FastAPI returns validation errors in JSON
        errors = response.json()["detail"]
        assert any(e["type"] == "less_than_equal" for e in errors)

    def test_run_options_extra_fields_ignored(self, client: TestClient, mock_agent_runner: AsyncMock):
        """Test extra fields are ignored (or rejected depending on config, default ignores)."""
        payload = {
            "message": "hello",
            "user_id": "test_user",
            "run_options": {
                "model": "gpt-4",
                "extra_field": "ignored"
            }
        }
        
        response = client.post("/chat", json=payload)
        assert response.status_code == 200
        
        call_args = mock_agent_runner.run.call_args
        _, kwargs = call_args
        run_opts = kwargs["run_options"]
        assert run_opts.model == "gpt-4"
        # Pydantic by default ignores extra fields


@pytest.mark.asyncio
async def test_agents_runtime_warms_up_and_closes_every_registered_agent() -> None:
    """``AgentsRuntime.start`` walks the registry warming up every runner;
    ``stop`` closes every runner's memory backend."""
    from types import SimpleNamespace

    from ark_agentic.core.protocol.bootstrap import Bootstrap
    from ark_agentic.core.runtime.agents_runtime import AgentsRuntime

    runner = AsyncMock()
    registry = MagicMock()
    registry.list_ids.return_value = ["insurance", "securities"]
    registry.get.return_value = runner

    with (
        patch("ark_agentic.agents.register_all"),
        patch("ark_agentic.plugins.api.deps.init_registry"),
    ):
        bootstrap = Bootstrap(
            [AgentsRuntime(registry=registry)], with_defaults=False,
        )
        await bootstrap.start(SimpleNamespace())
        await bootstrap.stop()

    assert runner.warmup.await_count == 2
    assert runner.close_memory.await_count == 2
