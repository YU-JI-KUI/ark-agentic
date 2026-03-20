"""Integration tests for create_insurance_agent() with LLM from env."""

from __future__ import annotations

import pytest

from ark_agentic.agents.insurance import create_insurance_agent


def test_create_insurance_agent_with_openai_compat_returns_runner_with_llm(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """create_insurance_agent with API_KEY and LLM_PROVIDER=openai returns runner with ChatOpenAI."""
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("API_KEY", "sk-test")
    monkeypatch.setenv("MODEL_NAME", "gpt-4o")
    monkeypatch.setenv("SESSIONS_DIR", str(tmp_path))

    runner = create_insurance_agent()

    assert runner is not None
    assert runner.llm is not None
    assert getattr(runner.llm, "model", None) == "gpt-4o"
