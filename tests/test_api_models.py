"""
Tests for api/models.py — Pydantic request/response models

Covers: serialization, validation, default values, and optional fields.
"""

from __future__ import annotations

import json

import pytest

from ark_agentic.api.models import (
    ChatRequest,
    ChatResponse,
    MessageItem,
    SessionCreateRequest,
    SessionHistoryResponse,
    SessionResponse,
    SSEEvent,
)


class TestChatRequest:
    """Chat request model validation."""

    def test_minimal_valid_request(self):
        """P0: Only 'message' is required."""
        req = ChatRequest(message="hello")
        assert req.message == "hello"
        assert req.agent_id == "insurance", "Default agent_id should be 'insurance'"
        assert req.stream is False
        assert req.session_id is None

    def test_full_request(self):
        """P0: All fields populated."""
        req = ChatRequest(
            agent_id="securities",
            message="查询持仓",
            session_id="sess-001",
            stream=True,
            protocol="agui",
            user_id="U001",
            context={"key": "value"},
            idempotency_key="idem-001",
        )
        assert req.agent_id == "securities"
        assert req.stream is True
        assert req.context == {"key": "value"}


class TestChatResponse:
    """Chat response model serialization."""

    def test_serialization(self):
        """P0: ChatResponse serializes correctly."""
        resp = ChatResponse(
            session_id="sess-001",
            response="Hello!",
            turns=1,
            usage={"prompt_tokens": 10, "completion_tokens": 5},
        )
        data = resp.model_dump()
        assert data["session_id"] == "sess-001"
        assert data["response"] == "Hello!"
        assert data["tool_calls"] == []
        assert data["turns"] == 1

    def test_default_tool_calls(self):
        """P1: tool_calls defaults to empty list."""
        resp = ChatResponse(session_id="s", response="r")
        assert resp.tool_calls == []


class TestSSEEvent:
    """SSE event model."""

    def test_template_event(self):
        """P0: Template event carries template data correctly."""
        template = {"template_type": "account_overview_card", "data": {"total": 100}}
        event = SSEEvent(
            type="response.template",
            seq=1,
            run_id="run-001",
            session_id="sess-001",
            template=template,
        )
        serialized = json.loads(event.model_dump_json(exclude_none=True))
        assert serialized["type"] == "response.template"
        assert serialized["template"]["template_type"] == "account_overview_card"

    def test_content_delta_event(self):
        """P0: Content delta event serialization."""
        event = SSEEvent(type="response.content.delta", seq=2, delta="Hello")
        assert event.delta == "Hello"
        assert event.template is None

    def test_failed_event(self):
        """P1: Failed event carries error message."""
        event = SSEEvent(type="response.failed", seq=99, error_message="timeout")
        assert event.error_message == "timeout"


class TestSessionModels:
    """Session-related models."""

    def test_session_create_request_defaults(self):
        """P0: Default agent_id is 'insurance'."""
        req = SessionCreateRequest()
        assert req.agent_id == "insurance"
        assert req.state is None

    def test_session_response(self):
        """P0: SessionResponse serialization."""
        resp = SessionResponse(session_id="s-001", message_count=5, state={"k": "v"})
        assert resp.session_id == "s-001"
        assert resp.message_count == 5

    def test_session_history_response(self):
        """P0: SessionHistoryResponse with message items."""
        msg = MessageItem(role="assistant", content="Hi", tool_calls=None)
        hist = SessionHistoryResponse(session_id="s-001", messages=[msg])
        assert len(hist.messages) == 1
        assert hist.messages[0].role == "assistant"
        assert hist.messages[0].content == "Hi"
