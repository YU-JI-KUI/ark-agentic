"""Tests for build_chat_request_meta helper used by /chat."""

from __future__ import annotations

from ark_agentic.api.chat import build_chat_request_meta
from ark_agentic.api.models import ChatRequest, HistoryMessage
from ark_agentic.core.types import RunOptions


def test_minimal_request_omits_defaults() -> None:
    req = ChatRequest(agent_id="ag", message="hi", user_id="u1")
    meta = build_chat_request_meta(req, message_id="m1", store_correlation=False)
    assert meta == {"agent_id": "ag", "message_id": "m1"}


def test_non_default_protocol_and_bu_stored() -> None:
    req = ChatRequest(
        agent_id="ag",
        message="hi",
        user_id="u",
        protocol="enterprise",
        source_bu_type="bu-x",
        app_type="app-y",
    )
    meta = build_chat_request_meta(req, message_id="m", store_correlation=False)
    assert meta["protocol"] == "enterprise"
    assert meta["source_bu_type"] == "bu-x"
    assert meta["app_type"] == "app-y"


def test_stream_true_stored() -> None:
    req = ChatRequest(agent_id="ag", message="hi", user_id="u", stream=True)
    meta = build_chat_request_meta(req, message_id="m", store_correlation=False)
    assert meta["stream"] is True


def test_stream_false_omitted() -> None:
    req = ChatRequest(agent_id="ag", message="hi", user_id="u", stream=False)
    meta = build_chat_request_meta(req, message_id="m", store_correlation=False)
    assert "stream" not in meta


def test_use_history_false_stored() -> None:
    req = ChatRequest(agent_id="ag", message="hi", user_id="u", use_history=False)
    meta = build_chat_request_meta(req, message_id="m", store_correlation=False)
    assert meta["use_history"] is False


def test_external_history_count_stored_only_when_present() -> None:
    req = ChatRequest(
        agent_id="ag",
        message="hi",
        user_id="u",
        history=[HistoryMessage(role="user", content="prev")],
    )
    meta = build_chat_request_meta(req, message_id="m", store_correlation=False)
    assert meta["external_history_count"] == 1


def test_idempotency_key_omitted_without_opt_in() -> None:
    req = ChatRequest(
        agent_id="ag", message="hi", user_id="u", idempotency_key="key-1"
    )
    meta = build_chat_request_meta(req, message_id="m", store_correlation=False)
    assert "idempotency_key" not in meta


def test_idempotency_key_stored_with_opt_in() -> None:
    req = ChatRequest(
        agent_id="ag", message="hi", user_id="u", idempotency_key="key-1"
    )
    meta = build_chat_request_meta(req, message_id="m", store_correlation=True)
    assert meta["idempotency_key"] == "key-1"


def test_run_options_model_provider_stored() -> None:
    req = ChatRequest(
        agent_id="ag",
        message="hi",
        user_id="u",
        run_options=RunOptions(model="custom-model"),
    )
    meta = build_chat_request_meta(req, message_id="m", store_correlation=False)
    assert meta["model"] == "custom-model"
    assert meta["has_run_options"] is True
