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


def test_create_chat_model_from_env_full_url_mode_rewrites_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LLM_BASE_URL_IS_FULL_URL=true wires rewrite transports and uses a placeholder base URL."""
    from ark_agentic.core.llm.debug_transport import RewriteURLAsyncTransport, RewriteURLTransport

    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("API_KEY", "sk-test")
    monkeypatch.setenv("MODEL_NAME", "gpt-4o")
    monkeypatch.setenv("LLM_BASE_URL", "https://service-host/chat/dialog")
    monkeypatch.setenv("LLM_BASE_URL_IS_FULL_URL", "true")

    llm = create_chat_model_from_env()

    assert llm is not None
    assert getattr(llm, "openai_api_base", None) == "https://service-host/"
    assert isinstance(getattr(llm, "http_client", None)._transport, RewriteURLTransport)  # type: ignore[union-attr]  # noqa: SLF001
    assert isinstance(getattr(llm, "http_async_client", None)._transport, RewriteURLAsyncTransport)  # type: ignore[union-attr]  # noqa: SLF001


def test_create_chat_model_from_env_full_url_mode_requires_llm_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LLM_BASE_URL_IS_FULL_URL=true requires a concrete LLM_BASE_URL value."""
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("API_KEY", "sk-test")
    monkeypatch.setenv("MODEL_NAME", "gpt-4o")
    monkeypatch.setenv("LLM_BASE_URL_IS_FULL_URL", "true")
    monkeypatch.delenv("LLM_BASE_URL", raising=False)

    with pytest.raises(ValueError, match="LLM_BASE_URL is required"):
        create_chat_model_from_env()


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


def test_create_chat_model_from_env_pa_sx_full_url_mode_rewrites_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PA-SX should reuse the same full-url rewrite path as OpenAI-compatible models."""
    from ark_agentic.core.llm.debug_transport import DebugTransport, RewriteURLAsyncTransport
    from ark_agentic.core.llm.pa_sx_llm import PASXTraceTransport

    monkeypatch.setenv("LLM_PROVIDER", "pa")
    monkeypatch.setenv("MODEL_NAME", "PA-SX-80B")
    monkeypatch.setenv("LLM_BASE_URL", "https://service-host/chat/dialog")
    monkeypatch.setenv("LLM_BASE_URL_IS_FULL_URL", "true")
    monkeypatch.setenv("API_KEY", "test-key")
    monkeypatch.setenv("PA_SX_80B_APP_ID", "test-app")

    llm = create_chat_model_from_env()

    assert llm is not None
    assert getattr(llm, "openai_api_base", None) == "https://service-host/"
    transport = getattr(llm, "http_async_client", None)._transport  # type: ignore[union-attr]  # noqa: SLF001
    assert isinstance(transport, PASXTraceTransport)
    inner = transport._transport  # noqa: SLF001
    if isinstance(inner, DebugTransport):
        inner = inner._inner  # noqa: SLF001
    assert isinstance(inner, RewriteURLAsyncTransport)


def test_create_chat_model_from_env_pa_jt_full_url_mode_rewrites_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PA-JT should also support LLM_BASE_URL_IS_FULL_URL via the shared endpoint resolver."""
    from ark_agentic.core.llm.debug_transport import DebugTransport, RewriteURLAsyncTransport
    from ark_agentic.core.llm.pa_jt_llm import PinganEAGWHeaderAsyncTransport

    monkeypatch.setenv("LLM_PROVIDER", "pa")
    monkeypatch.setenv("MODEL_NAME", "PA-JT-80B")
    monkeypatch.setenv("LLM_BASE_URL", "https://service-host/chat/dialog")
    monkeypatch.setenv("LLM_BASE_URL_IS_FULL_URL", "true")

    llm = create_chat_model_from_env()

    assert llm is not None
    assert getattr(llm, "openai_api_base", None) == "https://service-host/"
    transport = getattr(llm, "http_async_client", None)._transport  # type: ignore[union-attr]  # noqa: SLF001
    assert isinstance(transport, PinganEAGWHeaderAsyncTransport)
    inner = transport._transport  # noqa: SLF001
    if isinstance(inner, DebugTransport):
        inner = inner._inner  # noqa: SLF001
    assert isinstance(inner, RewriteURLAsyncTransport)
