"""Tests for build_chat_request_meta helper used by /chat."""

from __future__ import annotations

from ark_agentic.plugins.api.chat import build_chat_request_meta
from ark_agentic.plugins.api.models import ChatRequest, HistoryMessage
from ark_agentic.core.types import RunOptions


def test_minimal_request_omits_defaults() -> None:
    req = ChatRequest(agent_id="ag", message="hi", user_id="u1")
    meta = build_chat_request_meta(req, message_id="m1")
    assert meta == {"message_id": "m1"}


def test_agent_id_not_stored() -> None:
    req = ChatRequest(agent_id="ag", message="hi", user_id="u1")
    meta = build_chat_request_meta(req, message_id="m1")
    assert "agent_id" not in meta


def test_static_observability_fields_dropped() -> None:
    req = ChatRequest(
        agent_id="ag",
        message="hi",
        user_id="u",
        stream=True,
        protocol="enterprise",
        idempotency_key="key-1",
    )
    meta = build_chat_request_meta(req, message_id="m")
    assert "stream" not in meta
    assert "protocol" not in meta
    assert "idempotency_key" not in meta
    assert "has_run_options" not in meta


def test_caller_attribution_stored() -> None:
    req = ChatRequest(
        agent_id="ag",
        message="hi",
        user_id="u",
        source_bu_type="bu-x",
        app_type="app-y",
    )
    meta = build_chat_request_meta(req, message_id="m")
    assert meta["source_bu_type"] == "bu-x"
    assert meta["app_type"] == "app-y"


def test_use_history_false_stored() -> None:
    req = ChatRequest(agent_id="ag", message="hi", user_id="u", use_history=False)
    meta = build_chat_request_meta(req, message_id="m")
    assert meta["use_history"] is False


def test_external_history_count_stored_only_when_present() -> None:
    req = ChatRequest(
        agent_id="ag",
        message="hi",
        user_id="u",
        history=[HistoryMessage(role="user", content="prev")],
    )
    meta = build_chat_request_meta(req, message_id="m")
    assert meta["external_history_count"] == 1


def test_run_options_model_provider_stored() -> None:
    req = ChatRequest(
        agent_id="ag",
        message="hi",
        user_id="u",
        run_options=RunOptions(model="custom-model"),
    )
    meta = build_chat_request_meta(req, message_id="m")
    assert meta["model"] == "custom-model"
