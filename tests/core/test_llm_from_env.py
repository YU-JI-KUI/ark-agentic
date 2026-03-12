"""Unit tests for create_chat_model_from_env()."""

from __future__ import annotations

import pytest

from ark_agentic.core.llm.factory import create_chat_model_from_env


def test_create_chat_model_from_env_requires_model_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """MODEL_NAME not set raises ValueError mentioning MODEL_NAME."""
    monkeypatch.delenv("MODEL_NAME", raising=False)
    with pytest.raises(ValueError, match="MODEL_NAME"):
        create_chat_model_from_env()


def test_create_chat_model_from_env_openai_compat_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-pa provider without API_KEY raises with message containing API_KEY."""
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("MODEL_NAME", "gpt-4o")
    monkeypatch.delenv("API_KEY", raising=False)
    with pytest.raises(ValueError) as exc_info:
        create_chat_model_from_env()
    assert "API_KEY" in str(exc_info.value)


def test_create_chat_model_from_env_openai_compat_uses_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """OpenAI-compat path with API_KEY and MODEL_NAME creates ChatOpenAI."""
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("API_KEY", "sk-test")
    monkeypatch.setenv("MODEL_NAME", "gpt-4o")
    llm = create_chat_model_from_env()
    assert llm is not None
    assert getattr(llm, "model", None) == "gpt-4o"


def test_create_chat_model_from_env_openai_compat_uses_llm_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM_BASE_URL is passed through to ChatOpenAI when set."""
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("API_KEY", "sk-test")
    monkeypatch.setenv("MODEL_NAME", "gpt-4o")
    monkeypatch.setenv("LLM_BASE_URL", "https://custom.example.com/v1")
    llm = create_chat_model_from_env()
    assert llm is not None
    # LangChain ChatOpenAI exposes base URL as openai_api_base
    assert getattr(llm, "openai_api_base", None) == "https://custom.example.com/v1"


def test_create_chat_model_from_env_pa_invalid_model_name_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """PA provider with invalid MODEL_NAME raises ValueError, no silent fallback."""
    monkeypatch.setenv("LLM_PROVIDER", "pa")
    monkeypatch.setenv("MODEL_NAME", "Invalid-Model")
    monkeypatch.setenv("LLM_BASE_URL", "https://pa-sx.example.com")
    with pytest.raises(ValueError, match="Invalid-Model"):
        create_chat_model_from_env()


def test_create_chat_model_from_env_pa_valid_model_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """PA provider with valid MODEL_NAME=PA-SX-80B creates an LLM instance."""
    monkeypatch.setenv("LLM_PROVIDER", "pa")
    monkeypatch.setenv("MODEL_NAME", "PA-SX-80B")
    monkeypatch.setenv("LLM_BASE_URL", "https://pa-sx.example.com")
    monkeypatch.setenv("API_KEY", "test-key")
    monkeypatch.setenv("PA_SX_80B_APP_ID", "test-app")
    llm = create_chat_model_from_env()
    assert llm is not None
