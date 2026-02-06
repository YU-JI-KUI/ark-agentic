"""
PA Internal LLM Client Tests

测试 PAInternalClient 和相关功能
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from ark_agentic.core.llm import (
    PAModel,
    PAInternalClient,
    create_pa_client,
    create_llm_client,
)


# ============ PAModel Tests ============


class TestPAModel:
    """PAModel 枚举测试"""

    def test_model_values(self):
        """测试模型值"""
        assert PAModel.PA_JT_80B.value == "PA-JT-80B"
        assert PAModel.PA_SX_80B.value == "PA-SX-80B"
        assert PAModel.PA_SX_235B.value == "PA-SX-235B"

    def test_model_from_string(self):
        """测试从字符串创建"""
        assert PAModel("PA-JT-80B") == PAModel.PA_JT_80B
        assert PAModel("PA-SX-80B") == PAModel.PA_SX_80B
        assert PAModel("PA-SX-235B") == PAModel.PA_SX_235B

    def test_model_invalid_string(self):
        """测试无效字符串"""
        with pytest.raises(ValueError):
            PAModel("invalid-model")


# ============ PAInternalClient Tests ============


class TestPAInternalClient:
    """PAInternalClient 测试"""

    def test_init_sx_model_requires_base_url(self):
        """测试 SX 模型需要 base_url"""
        # 清除环境变量
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError, match="PA_SX_BASE_URL"):
                PAInternalClient(PAModel.PA_SX_80B)

    def test_init_jt_model_requires_base_url(self):
        """测试 JT 模型需要 base_url"""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError, match="PA_JT_BASE_URL"):
                PAInternalClient(PAModel.PA_JT_80B)

    def test_init_sx_model_success(self):
        """测试 SX 模型成功初始化"""
        env = {
            "PA_SX_BASE_URL": "https://sx-api.example.com/v1",
            "PA_SX_API_KEY": "sk-test",
            "PA_SX_80B_APP_ID": "test-app-80b",
        }
        with patch.dict(os.environ, env, clear=True):
            client = PAInternalClient(PAModel.PA_SX_80B)
            assert client.pa_model == PAModel.PA_SX_80B
            assert client.model_config.model_type == "sx"
            assert client.model_config.trace_app_id == "test-app-80b"

    def test_init_jt_model_success(self):
        """测试 JT 模型成功初始化"""
        env = {
            "PA_JT_BASE_URL": "https://jt-api.example.com/v1",
            "PA_JT_OPEN_API_CODE": "test-code",
            "PA_JT_OPEN_API_CREDENTIAL": "test-cred",
        }
        with patch.dict(os.environ, env, clear=True):
            client = PAInternalClient(PAModel.PA_JT_80B)
            assert client.pa_model == PAModel.PA_JT_80B
            assert client.model_config.model_type == "jt"

    def test_init_from_string(self):
        """测试从字符串初始化"""
        env = {"PA_SX_BASE_URL": "https://sx-api.example.com/v1"}
        with patch.dict(os.environ, env, clear=True):
            client = PAInternalClient("PA-SX-80B")
            assert client.pa_model == PAModel.PA_SX_80B

    def test_init_invalid_model_string(self):
        """测试无效模型字符串"""
        with pytest.raises(ValueError, match="Unknown PA model"):
            PAInternalClient("invalid-model")

    @pytest.mark.asyncio
    async def test_chat_sx_model_request(self):
        """测试 SX 模型请求格式"""
        env = {
            "PA_SX_BASE_URL": "https://sx-api.example.com/v1",
            "PA_SX_API_KEY": "sk-test",
            "PA_SX_80B_APP_ID": "test-app-80b",
        }
        with patch.dict(os.environ, env, clear=True):
            client = PAInternalClient(PAModel.PA_SX_80B)

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
                "ok": True,
                "code": 200,
                "msg": "success",
            }
            mock_response.raise_for_status = MagicMock()

            with patch.object(
                httpx.AsyncClient,
                "post",
                new_callable=AsyncMock,
                return_value=mock_response,
            ) as mock_post:
                client._client = httpx.AsyncClient()

                messages = [{"role": "user", "content": "Hi"}]
                result = await client.chat(messages, stream=False)

                # 验证请求
                mock_post.assert_called_once()
                call_kwargs = mock_post.call_args.kwargs
                headers = call_kwargs.get("headers", {})

                # 验证 headers
                assert headers.get("Authorization") == "Bearer sk-test"
                assert headers.get("trace-appId") == "test-app-80b"

                # 验证返回
                assert result["choices"][0]["message"]["content"] == "Hello!"
                assert result.get("ok") is True

            await client.close()

    @pytest.mark.asyncio
    async def test_chat_jt_model_request(self):
        """测试 JT 模型请求格式"""
        env = {
            "PA_JT_BASE_URL": "https://jt-api.example.com/v1",
            "PA_JT_OPEN_API_CODE": "test-code",
            "PA_JT_OPEN_API_CREDENTIAL": "test-cred",
            "PA_JT_GPT_APP_KEY": "test-app-key",
            "PA_JT_GPT_APP_SECRET": "test-app-secret",
            "PA_JT_SCENE_ID": "test-scene",
        }
        with patch.dict(os.environ, env, clear=True):
            client = PAInternalClient(PAModel.PA_JT_80B)

            # Mock response
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "id": "chat-123",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "Hello from JT!"},
                        "finish_reason": "stop",
                    }
                ],
            }
            mock_response.raise_for_status = MagicMock()

            with patch.object(
                httpx.AsyncClient,
                "post",
                new_callable=AsyncMock,
                return_value=mock_response,
            ) as mock_post:
                client._client = httpx.AsyncClient()

                messages = [{"role": "user", "content": "Hi"}]
                result = await client.chat(messages, stream=False)

                # 验证请求
                mock_post.assert_called_once()
                call_kwargs = mock_post.call_args.kwargs
                headers = call_kwargs.get("headers", {})
                body = call_kwargs.get("json", {})

                # 验证 JT headers
                assert headers.get("openAPICode") == "test-code"
                assert headers.get("openAPICredential") == "test-cred"
                assert headers.get("gpt_app_key") == "test-app-key"
                assert "openAPIRequestTime" in headers
                assert "openAPISignature" in headers
                assert "gpt_signature" in headers

                # 验证 JT body
                assert "request_id" in body
                assert body.get("scene_id") == "test-scene"
                assert body.get("seed") == 42

                # 验证返回
                assert result["choices"][0]["message"]["content"] == "Hello from JT!"

            await client.close()

    @pytest.mark.asyncio
    async def test_chat_with_thinking_kwargs(self):
        """测试 thinking 参数"""
        env = {
            "PA_JT_BASE_URL": "https://jt-api.example.com/v1",
        }
        with patch.dict(os.environ, env, clear=True):
            client = PAInternalClient(PAModel.PA_JT_80B)

            # Mock response
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "choices": [
                    {"message": {"role": "assistant", "content": "Thinking..."}}
                ]
            }
            mock_response.raise_for_status = MagicMock()

            with patch.object(
                httpx.AsyncClient,
                "post",
                new_callable=AsyncMock,
                return_value=mock_response,
            ) as mock_post:
                client._client = httpx.AsyncClient()

                messages = [{"role": "user", "content": "Hi"}]
                await client.chat(
                    messages,
                    stream=False,
                    chat_template_kwargs={"enable_thinking": True, "thinking": True},
                )

                # 验证 body 包含 chat_template_kwargs
                call_kwargs = mock_post.call_args.kwargs
                body = call_kwargs.get("json", {})
                assert body.get("chat_template_kwargs") == {
                    "enable_thinking": True,
                    "thinking": True,
                }

            await client.close()


# ============ Factory Function Tests ============


class TestFactoryFunctions:
    """工厂函数测试"""

    def test_create_pa_client(self):
        """测试 create_pa_client"""
        env = {"PA_SX_BASE_URL": "https://sx-api.example.com/v1"}
        with patch.dict(os.environ, env, clear=True):
            client = create_pa_client()
            assert isinstance(client, PAInternalClient)
            assert client.pa_model == PAModel.PA_SX_80B

    def test_create_pa_client_with_model(self):
        """测试 create_pa_client 指定模型"""
        env = {"PA_SX_BASE_URL": "https://sx-api.example.com/v1"}
        with patch.dict(os.environ, env, clear=True):
            client = create_pa_client(model=PAModel.PA_SX_235B)
            assert client.pa_model == PAModel.PA_SX_235B

    def test_create_pa_client_with_string_model(self):
        """测试 create_pa_client 字符串模型"""
        env = {"PA_SX_BASE_URL": "https://sx-api.example.com/v1"}
        with patch.dict(os.environ, env, clear=True):
            client = create_pa_client(model="PA-SX-235B")
            assert client.pa_model == PAModel.PA_SX_235B

    def test_create_llm_client_pa_provider(self):
        """测试 create_llm_client pa provider"""
        env = {"PA_SX_BASE_URL": "https://sx-api.example.com/v1"}
        with patch.dict(os.environ, env, clear=True):
            client = create_llm_client(provider="pa")
            assert isinstance(client, PAInternalClient)

    def test_create_llm_client_pa_with_model(self):
        """测试 create_llm_client pa 指定模型"""
        env = {"PA_JT_BASE_URL": "https://jt-api.example.com/v1"}
        with patch.dict(os.environ, env, clear=True):
            client = create_llm_client(provider="pa", pa_model=PAModel.PA_JT_80B)
            assert isinstance(client, PAInternalClient)
            assert client.pa_model == PAModel.PA_JT_80B

    def test_create_llm_client_default_is_pa(self):
        """测试 create_llm_client 默认是 PA"""
        env = {"PA_SX_BASE_URL": "https://sx-api.example.com/v1"}
        with patch.dict(os.environ, env, clear=True):
            client = create_llm_client()
            assert isinstance(client, PAInternalClient)
