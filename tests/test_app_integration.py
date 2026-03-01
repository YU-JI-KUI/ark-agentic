"""Integration tests for API and RunOptions."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from ark_agentic.app import app
from ark_agentic.core.runner import AgentRunner, RunResult
from ark_agentic.core.types import AgentMessage, MessageRole


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)

@pytest.fixture
def mock_agent_runner():
    """Mock the insurance agent runner."""
    with patch("ark_agentic.api.chat._get_agent") as mock_get:
        runner = AsyncMock(spec=AgentRunner)
        # Mock session manager
        runner.session_manager = AsyncMock()
        runner.session_manager.create_session.return_value = AsyncMock(session_id="test-session")
        runner.session_manager.get_session.return_value = AsyncMock(session_id="test-session")
        runner.session_manager.load_session.return_value = AsyncMock(session_id="test-session")
        
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
