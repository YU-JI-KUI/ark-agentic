"""
LLM Internal Clients Tests

测试 InternalAPIClient 和 SimpleInternalClient
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from ark_agentic.core.llm import (
    LLMConfig,
    InternalAPIClient,
    SimpleInternalClient,
    create_internal_client,
    create_simple_client,
    create_llm_client,
)


# ============ Fixtures ============


@pytest.fixture
def internal_config() -> LLMConfig:
    """Internal client 配置"""
    return LLMConfig(
        provider="internal",
        base_url="https://my-llm/api-app/agent/v1/chat/completions",
        authorization="Bearer sk-test",
        trace_appid="test-app",
        trace_source="test-source",
        trace_user_id="test-user",
    )


@pytest.fixture
def simple_config() -> LLMConfig:
    """Simple client 配置"""
    return LLMConfig(
        provider="simple",
        base_url="https://my-llm/simple-api",
        authorization="Bearer sk-test",
    )


# ============ InternalAPIClient Tests ============


class TestInternalAPIClient:
    """InternalAPIClient 测试"""

    def test_init_requires_base_url(self):
        """测试初始化需要 base_url"""
        config = LLMConfig(
            provider="internal",
            authorization="Bearer test",
            trace_appid="test",
        )
        with pytest.raises(ValueError, match="base_url is required"):
            InternalAPIClient(config)

    def test_init_requires_authorization(self):
        """测试初始化需要 authorization"""
        config = LLMConfig(
            provider="internal",
            base_url="https://test.com",
            trace_appid="test",
        )
        with pytest.raises(ValueError, match="authorization is required"):
            InternalAPIClient(config)

    def test_init_requires_trace_appid(self):
        """测试初始化需要 trace_appid"""
        config = LLMConfig(
            provider="internal",
            base_url="https://test.com",
            authorization="Bearer test",
        )
        with pytest.raises(ValueError, match="trace_appid is required"):
            InternalAPIClient(config)

    def test_init_success(self, internal_config: LLMConfig):
        """测试成功初始化"""
        client = InternalAPIClient(internal_config)
        assert client.base_url == "https://my-llm/api-app/agent/v1/chat/completions"
        assert client.authorization == "Bearer sk-test"
        assert client.trace_appid == "test-app"
        assert client.trace_source == "test-source"
        assert client.trace_user_id == "test-user"

    @pytest.mark.asyncio
    async def test_chat_sync_request_format(self, internal_config: LLMConfig):
        """测试同步请求格式"""
        client = InternalAPIClient(internal_config)

        # Mock response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "chat-123",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "Hello!"},
                    "finish_reason": "stop",
                }
            ],
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(
            httpx.AsyncClient, "post", new_callable=AsyncMock, return_value=mock_response
        ) as mock_post:
            client._client = httpx.AsyncClient()

            messages = [{"role": "user", "content": "Hi"}]
            result = await client.chat(messages, stream=False)

            # 验证请求
            mock_post.assert_called_once()
            call_kwargs = mock_post.call_args.kwargs
            body = call_kwargs["json"]

            # 验证 body 格式
            assert "reqId" in body
            assert body["stream"] is False
            assert "messages" in body
            assert body["messages"] == [{"role": "user", "content": "Hi"}]

            # 验证返回
            assert result["choices"][0]["message"]["content"] == "Hello!"

        await client.close()

    @pytest.mark.asyncio
    async def test_chat_headers(self, internal_config: LLMConfig):
        """测试请求 headers"""
        client = InternalAPIClient(internal_config)

        # 获取 client
        http_client = await client._get_client()

        # 验证 headers（使用驼峰格式）
        assert http_client.headers["Content-Type"] == "application/json"
        assert http_client.headers["Authorization"] == "Bearer sk-test"
        assert http_client.headers["trace-appId"] == "test-app"
        assert http_client.headers["trace-source"] == "test-source"
        assert http_client.headers["trace-userId"] == "test-user"

        await client.close()

    @pytest.mark.asyncio
    async def test_normalize_response(self, internal_config: LLMConfig):
        """测试响应标准化"""
        client = InternalAPIClient(internal_config)

        raw_response = {
            "id": "chat-123",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "Test response"},
                }
            ],
        }

        normalized = client._normalize_response(raw_response)

        assert normalized["id"] == "chat-123"
        assert "choices" in normalized
        assert normalized["choices"][0]["message"]["role"] == "assistant"
        assert normalized["choices"][0]["message"]["content"] == "Test response"

        await client.close()


# ============ SimpleInternalClient Tests ============


class TestSimpleInternalClient:
    """SimpleInternalClient 测试"""

    def test_init_requires_base_url(self):
        """测试初始化需要 base_url"""
        config = LLMConfig(provider="simple")
        with pytest.raises(ValueError, match="base_url is required"):
            SimpleInternalClient(config)

    def test_init_success_without_auth(self):
        """测试不需要 authorization 也能初始化"""
        config = LLMConfig(
            provider="simple",
            base_url="https://test.com",
        )
        client = SimpleInternalClient(config)
        assert client.base_url == "https://test.com"
        assert client.authorization == ""

    def test_init_success_with_auth(self, simple_config: LLMConfig):
        """测试带 authorization 初始化"""
        client = SimpleInternalClient(simple_config)
        assert client.base_url == "https://my-llm/simple-api"
        assert client.authorization == "Bearer sk-test"

    @pytest.mark.asyncio
    async def test_chat_request_format(self, simple_config: LLMConfig):
        """测试请求格式 - 使用 messages 数组"""
        client = SimpleInternalClient(simple_config)

        # Mock response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"content": "Hello! I'm good, thanks!"}
        mock_response.raise_for_status = MagicMock()

        with patch.object(
            httpx.AsyncClient, "post", new_callable=AsyncMock, return_value=mock_response
        ) as mock_post:
            client._client = httpx.AsyncClient()

            messages = [{"role": "user", "content": "Hi, how are you?"}]
            result = await client.chat(messages)

            # 验证请求
            mock_post.assert_called_once()
            call_kwargs = mock_post.call_args.kwargs
            body = call_kwargs["json"]

            # 验证 body 格式 - 使用 messages 数组
            assert "messages" in body
            assert body["messages"] == [{"role": "user", "content": "Hi, how are you?"}]
            assert body["stream"] is False

            # 验证返回（应该是 OpenAI 格式）
            assert "choices" in result
            assert result["choices"][0]["message"]["content"] == "Hello! I'm good, thanks!"

        await client.close()

    @pytest.mark.asyncio
    async def test_chat_stream_request(self, simple_config: LLMConfig):
        """测试流式请求"""
        client = SimpleInternalClient(simple_config)

        messages = [{"role": "user", "content": "Hi"}]
        body_captured = {}

        # Mock stream response using MagicMock with async context manager
        class MockStreamResponse:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            def raise_for_status(self):
                pass

            async def aiter_lines(self):
                yield 'data: {"choices": [{"delta": {"content": "Hello"}}]}'
                yield 'data: {"choices": [{"delta": {"content": "!"}}]}'
                yield "data: [DONE]"

        def mock_stream(*args, **kwargs):
            body_captured.update(kwargs.get("json", {}))
            return MockStreamResponse()

        with patch.object(httpx.AsyncClient, "stream", side_effect=mock_stream):
            client._client = httpx.AsyncClient()

            result = await client.chat(messages, stream=True)
            chunks = [chunk async for chunk in result]

            # 验证请求 body 格式
            assert body_captured["stream"] is True
            assert body_captured["messages"] == [{"role": "user", "content": "Hi"}]

            # 验证 chunks
            assert len(chunks) == 2
            assert chunks[0]["choices"][0]["delta"]["content"] == "Hello"
            assert chunks[1]["choices"][0]["delta"]["content"] == "!"

        await client.close()

    @pytest.mark.asyncio
    async def test_normalize_response(self, simple_config: LLMConfig):
        """测试响应标准化"""
        client = SimpleInternalClient(simple_config)

        # 测试字符串 content
        raw_response = {"content": "Simple response"}
        normalized = client._normalize_response(raw_response)

        assert "choices" in normalized
        assert normalized["choices"][0]["message"]["role"] == "assistant"
        assert normalized["choices"][0]["message"]["content"] == "Simple response"

        # 测试已有 choices 格式
        raw_response2 = {
            "choices": [
                {"index": 0, "message": {"role": "assistant", "content": "Already formatted"}}
            ]
        }
        normalized2 = client._normalize_response(raw_response2)
        assert normalized2["choices"][0]["message"]["content"] == "Already formatted"

        await client.close()


# ============ Factory Function Tests ============


class TestFactoryFunctions:
    """工厂函数测试"""

    def test_create_internal_client(self):
        """测试 create_internal_client"""
        client = create_internal_client(
            base_url="https://test.com",
            authorization="Bearer test",
            trace_appid="test-app",
            trace_source="test-source",
            trace_user_id="test-user",
        )
        assert isinstance(client, InternalAPIClient)
        assert client.base_url == "https://test.com"
        assert client.trace_appid == "test-app"
        assert client.trace_source == "test-source"
        assert client.trace_user_id == "test-user"

    def test_create_simple_client(self):
        """测试 create_simple_client"""
        client = create_simple_client(
            base_url="https://test.com",
            authorization="Bearer test",
        )
        assert isinstance(client, SimpleInternalClient)
        assert client.base_url == "https://test.com"

    def test_create_simple_client_no_auth(self):
        """测试 create_simple_client 不带 auth"""
        client = create_simple_client(base_url="https://test.com")
        assert isinstance(client, SimpleInternalClient)
        assert client.authorization == ""

    def test_create_llm_client_internal(self):
        """测试 create_llm_client internal"""
        client = create_llm_client(
            provider="internal",
            base_url="https://test.com",
            authorization="Bearer test",
            trace_appid="test-app",
        )
        assert isinstance(client, InternalAPIClient)

    def test_create_llm_client_simple(self):
        """测试 create_llm_client simple"""
        client = create_llm_client(
            provider="simple",
            base_url="https://test.com",
        )
        assert isinstance(client, SimpleInternalClient)

    def test_create_llm_client_internal_requires_params(self):
        """测试 create_llm_client internal 需要参数"""
        with pytest.raises(ValueError, match="base_url is required"):
            create_llm_client(provider="internal")

        with pytest.raises(ValueError, match="authorization is required"):
            create_llm_client(provider="internal", base_url="https://test.com")

        with pytest.raises(ValueError, match="trace_appid is required"):
            create_llm_client(
                provider="internal",
                base_url="https://test.com",
                authorization="Bearer test",
            )

    def test_create_llm_client_simple_requires_base_url(self):
        """测试 create_llm_client simple 需要 base_url"""
        with pytest.raises(ValueError, match="base_url is required"):
            create_llm_client(provider="simple")
