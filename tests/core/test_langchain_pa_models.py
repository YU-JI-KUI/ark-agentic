"""
LangChain PA Models Integration Tests

测试 LangChain 集成后的 PA 模型功能
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ark_agentic.core.llm.factory import create_chat_model
from ark_agentic.core.llm.protocol import LangChainLLMProtocol


class TestPAModelsLangChain:
    """测试 PA 模型通过 LangChain 的集成"""

    @pytest.mark.asyncio
    async def test_pa_sx_model_creation(self):
        """测试 PA-SX 模型创建"""
        with patch.dict(os.environ, {"PA_GATEWAY_URL": "http://test.com"}):
            model = create_chat_model("PA-SX-80B")
            assert isinstance(model, LangChainLLMProtocol)

    @pytest.mark.asyncio
    async def test_pa_jt_model_creation(self):
        """测试 PA-JT 模型创建"""
        with patch.dict(os.environ, {
            "PA_GATEWAY_URL": "http://test.com",
            "PA_APP_ID": "test_app",
            "PA_PRIVATE_KEY": "test_key"
        }):
            model = create_chat_model("PA-JT-80B")
            assert isinstance(model, LangChainLLMProtocol)

    @pytest.mark.asyncio
    async def test_graceful_fallback_to_mock(self):
        """测试优雅降级到 Mock LLM"""
        # 清除环境变量，强制降级
        with patch.dict(os.environ, {}, clear=True):
            model = create_chat_model("PA-SX-80B")
            # 应该降级到 MockLLMWrapper
            assert model.__class__.__name__ == 'MockLLMWrapper'

    @pytest.mark.asyncio
    async def test_deepseek_model_creation(self):
        """测试 DeepSeek 模型创建"""
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test_key"}):
            model = create_chat_model("deepseek-chat")
            assert isinstance(model, LangChainLLMProtocol)

    @pytest.mark.asyncio
    async def test_model_invoke_interface(self):
        """测试模型调用接口"""
        model = create_chat_model("mock")

        messages = [{"role": "user", "content": "Hello"}]

        # 测试 ainvoke 方法存在
        assert hasattr(model, 'ainvoke')
        assert hasattr(model, 'astream')
        assert hasattr(model, 'bind_tools')

    @pytest.mark.asyncio
    async def test_tool_binding_interface(self):
        """测试工具绑定接口"""
        model = create_chat_model("mock")

        tools = [{"type": "function", "function": {"name": "test_tool"}}]
        bound_model = model.bind_tools(tools)

        assert isinstance(bound_model, LangChainLLMProtocol)