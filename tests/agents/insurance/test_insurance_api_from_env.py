"""Integration tests for create_insurance_agent_from_env() with LLM from env."""

from __future__ import annotations

import pytest

from ark_agentic.agents.insurance.api import create_insurance_agent_from_env


def test_create_insurance_agent_from_env_with_openai_compat_returns_runner_with_llm(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """create_insurance_agent_from_env with API_KEY and LLM_PROVIDER=openai returns runner with ChatOpenAI."""
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("API_KEY", "sk-test")
    monkeypatch.setenv("MODEL_NAME", "gpt-4o")

    runner = create_insurance_agent_from_env(
        sessions_dir=tmp_path,
        enable_persistence=True,
    )

    assert runner is not None
    assert runner.llm is not None
    assert getattr(runner.llm, "model", None) == "gpt-4o"
