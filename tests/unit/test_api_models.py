"""
Tests for api/models.py — Pydantic request/response models

Covers: serialization, validation, default values, and optional fields.
"""

from __future__ import annotations

import json

import pytest

from ark_agentic.plugins.api.models import (
    ChatRequest,
    ChatResponse,
    HistoryMessage,
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
            message_id="msg-001",
            context={"key": "value"},
            idempotency_key="idem-001",
        )
        assert req.agent_id == "securities"
        assert req.stream is True
        assert req.context == {"key": "value"}
        assert req.message_id == "msg-001"

    def test_message_id_optional(self):
        """P1: message_id 可选，默认 None."""
        req = ChatRequest(message="hi")
        assert req.message_id is None
        req_with = ChatRequest(message="hi", message_id="custom-id")
        assert req_with.message_id == "custom-id"

    def test_history_and_use_history(self):
        """P1: history / use_history 可选，默认 use_history=True。"""
        req = ChatRequest(message="hi")
        assert req.history is None
        assert req.use_history is True
        req_with_history = ChatRequest(
            message="hi",
            history=[
                HistoryMessage(role="user", content="外部问题"),
                HistoryMessage(role="assistant", content="外部回答"),
            ],
            use_history=False,
        )
        assert len(req_with_history.history) == 2
        assert req_with_history.history[0].role == "user"
        assert req_with_history.history[0].content == "外部问题"
        assert req_with_history.use_history is False

    def test_history_accepts_json_string(self):
        """P1: history 可为 JSON 字符串，解析后与 array 一致。"""
        payload = [{"role": "user", "content": "你好"}, {"role": "assistant", "content": "您好"}]
        req = ChatRequest(message="hi", history=json.dumps(payload))
        assert req.history is not None
        assert len(req.history) == 2
        assert req.history[0].role == "user"
        assert req.history[0].content == "你好"
        assert req.history[1].role == "assistant"
        assert req.history[1].content == "您好"

    def test_history_invalid_json_string_raises(self):
        """P2: history 为非法 JSON 字符串时抛出 ValueError。"""
        with pytest.raises(ValueError, match="history: invalid JSON"):
            ChatRequest(message="hi", history="not json")

    def test_history_json_string_must_be_list(self):
        """P2: history JSON 字符串必须为数组，否则抛出 ValueError。"""
        with pytest.raises(ValueError, match="history: JSON string must be a list"):
            ChatRequest(message="hi", history='{"role":"user","content":"x"}')


class TestHistoryMessage:
    """HistoryMessage model for external chat history."""

    def test_valid_roles(self):
        """P0: role must be user or assistant."""
        u = HistoryMessage(role="user", content="hi")
        a = HistoryMessage(role="assistant", content="ok")
        assert u.role == "user"
        assert a.role == "assistant"

    def test_model_dump_for_runner(self):
        """P0: model_dump yields dict expected by merge layer."""
        m = HistoryMessage(role="user", content="hello")
        d = m.model_dump()
        assert d == {"role": "user", "content": "hello"}


class TestChatResponse:
    """Chat response model serialization."""

    def test_serialization(self):
        """P0: ChatResponse serializes correctly."""
        resp = ChatResponse(
            session_id="sess-001",
            message_id="msg-001",
            response="Hello!",
            turns=1,
        )
        data = resp.model_dump()
        assert data["session_id"] == "sess-001"
        assert data["message_id"] == "msg-001"
        assert data["response"] == "Hello!"
        assert data["tool_calls"] == []
        assert data["turns"] == 1

    def test_default_tool_calls(self):
        """P1: tool_calls defaults to empty list."""
        resp = ChatResponse(session_id="s", message_id="m", response="r")
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
