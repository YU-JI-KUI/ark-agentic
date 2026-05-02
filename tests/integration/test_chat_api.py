"""
Chat API 端点测试 — Phase 1 契约：user_id 必传、message_id 解析、header 命名。

覆盖：user_id 缺失 400、user_id 从 header、message_id 从 body/header/自动生成并回写响应。
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from ark_agentic.app import app
from ark_agentic.api import deps
from ark_agentic.core.registry import AgentRegistry
from ark_agentic.core.runner import RunResult
from ark_agentic.core.types import AgentMessage, MessageRole


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(autouse=True)
def _init_registry():
    deps.init_registry(AgentRegistry())
    yield


@pytest.fixture
def mock_runner():
    from ark_agentic.core.types import SessionEntry
    with patch("ark_agentic.api.chat.get_agent") as mock_get:
        runner = AsyncMock()
        runner.session_manager = MagicMock()
        mock_session = SessionEntry(
            session_id="test-session",
            model="mock",
            provider="mock",
            state={},
            active_skill_ids=[],
            messages=[],
        )

        async def mock_create_session(user_id: str, **kwargs):
            return mock_session

        async def mock_load_session(session_id: str, user_id: str, **kwargs):
            return mock_session

        runner.session_manager.create_session = mock_create_session
        runner.session_manager.load_session = mock_load_session
        runner.session_manager.get_session.return_value = mock_session

        runner.run.return_value = RunResult(
            response=AgentMessage(role=MessageRole.ASSISTANT, content="OK"),
            turns=1,
            prompt_tokens=0,
            completion_tokens=0,
        )
        mock_get.return_value = runner
        yield runner



class TestChatUserIdRequired:
    """P0: user_id 必传，缺失时 400."""

    def test_missing_user_id_returns_400(self, client: TestClient, mock_runner) -> None:
        """Body 和 header 均无 user_id 时返回 400（需 patch get_agent 否则先 404）。"""
        payload = {"message": "hello"}
        response = client.post("/chat", json=payload)
        assert response.status_code == 400, response.json()
        data = response.json()
        assert "detail" in data
        assert "user_id" in data["detail"].lower() or "user" in data["detail"].lower()

    def test_user_id_in_body_succeeds(self, client: TestClient, mock_runner) -> None:
        """Body 提供 user_id 时请求成功."""
        payload = {"message": "hi", "user_id": "U001"}
        response = client.post("/chat", json=payload)
        assert response.status_code == 200
        call_kwargs = mock_runner.run.call_args[1]
        assert call_kwargs["user_id"] == "U001"

    def test_user_id_from_header_succeeds(self, client: TestClient, mock_runner) -> None:
        """Header x-ark-user-id 提供 user_id 时请求成功（body 无 user_id）。"""
        payload = {"message": "hi"}
        headers = {"x-ark-user-id": "U-header"}
        response = client.post("/chat", json=payload, headers=headers)
        assert response.status_code == 200
        call_kwargs = mock_runner.run.call_args[1]
        assert call_kwargs["user_id"] == "U-header"

    def test_user_id_body_overrides_header(self, client: TestClient, mock_runner) -> None:
        """Body user_id 与 header 同时存在时以 body 为准."""
        payload = {"message": "hi", "user_id": "U-body"}
        headers = {"x-ark-user-id": "U-header"}
        response = client.post("/chat", json=payload, headers=headers)
        assert response.status_code == 200
        call_kwargs = mock_runner.run.call_args[1]
        assert call_kwargs["user_id"] == "U-body"


class TestChatMessageId:
    """P0: message_id 可选，响应中必须带回（body > header > 自动 UUID）。"""

    def test_message_id_in_response_from_body(
        self, client: TestClient, mock_runner
    ) -> None:
        """Body 提供 message_id 时，响应中返回相同值."""
        payload = {
            "message": "hi",
            "user_id": "U1",
            "message_id": "msg-from-body-001",
        }
        response = client.post("/chat", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["message_id"] == "msg-from-body-001"

    def test_message_id_in_response_from_header(
        self, client: TestClient, mock_runner
    ) -> None:
        """Header x-ark-message-id 提供时，响应中返回该值（body 无 message_id）。"""
        payload = {"message": "hi", "user_id": "U1"}
        headers = {"x-ark-message-id": "msg-from-header-002"}
        response = client.post("/chat", json=payload, headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data["message_id"] == "msg-from-header-002"

    def test_message_id_auto_generated_when_absent(
        self, client: TestClient, mock_runner
    ) -> None:
        """Body 和 header 均无 message_id 时，响应中为合法 UUID."""
        payload = {"message": "hi", "user_id": "U1"}
        response = client.post("/chat", json=payload)
        assert response.status_code == 200
        data = response.json()
        mid = data["message_id"]
        assert mid, "message_id must be non-empty"
        uuid.UUID(mid)

    def test_message_id_body_overrides_header(
        self, client: TestClient, mock_runner
    ) -> None:
        """Body message_id 与 header 同时存在时以 body 为准."""
        payload = {
            "message": "hi",
            "user_id": "U1",
            "message_id": "body-msg",
        }
        headers = {"x-ark-message-id": "header-msg"}
        response = client.post("/chat", json=payload, headers=headers)
        assert response.status_code == 200
        assert response.json()["message_id"] == "body-msg"


class TestChatSessionIdHeader:
    """P1: x-ark-session-id header 用于提供 session_id."""

    def test_session_id_from_header(
        self, client: TestClient, mock_runner
    ) -> None:
        """x-ark-session-id 提供时，用于解析会话（get_agent 返回的 runner 会 load_session）。"""
        payload = {"message": "hi", "user_id": "U1"}
        headers = {"x-ark-session-id": "sess-header-123"}
        response = client.post("/chat", json=payload, headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data["session_id"] == "sess-header-123"


