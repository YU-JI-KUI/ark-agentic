"""Integration tests for ``InsuranceAgent`` with LLM from env."""

from __future__ import annotations

import pytest

from ark_agentic.agents.insurance import InsuranceAgent


def test_insurance_agent_with_openai_env_wires_chat_model(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """InsuranceAgent() with API_KEY + LLM_PROVIDER=openai pulls ChatOpenAI from env."""
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("API_KEY", "sk-test")
    monkeypatch.setenv("MODEL_NAME", "gpt-4o")
    monkeypatch.setenv("SESSIONS_DIR", str(tmp_path))

    agent = InsuranceAgent()

    assert agent is not None
    assert agent.llm is not None
    assert getattr(agent.llm, "model", None) == "gpt-4o"
