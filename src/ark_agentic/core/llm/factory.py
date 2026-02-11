"""
LLM Client 工厂

提供统一的客户端创建接口。
"""

from __future__ import annotations

import os
from typing import Any, Literal

from .base import LLMClientProtocol, LLMConfig
from .openai_compat import OpenAICompatibleClient
from .pa_internal_llm import PAModel, create_pa_client
from .mock import MockLLMClient


# ============ 环境变量名 ============

ENV_KEYS = {
    "deepseek": "DEEPSEEK_API_KEY",
}


def create_llm_client(
    provider: Literal["deepseek", "pa", "mock"] = "pa",
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    # PA 专用参数
    pa_model: str | PAModel = PAModel.PA_SX_80B,
    # 扩展参数（用于 OpenAI 兼容 API 添加自定义 headers/body）
    extra_headers: dict[str, Any] | None = None,
    extra_body: dict[str, Any] | None = None,
    # 其他配置
    **kwargs: Any,
) -> LLMClientProtocol:
    """创建 LLM 客户端

    Args:
        provider: 提供商 ("pa", "deepseek", "mock")
        api_key: API Key（从环境变量读取或显式传入）
        base_url: API 端点（可选）
        model: 模型名称（可选）
        pa_model: PA 模型选择（PA-JT-80B, PA-SX-80B, PA-SX-235B）
        extra_headers: 额外 HTTP headers（静态值或 Callable 动态值）
        extra_body: 额外 body 参数（静态值或 Callable 动态值）
        **kwargs: 其他配置参数

    Returns:
        LLM 客户端实例

    Examples:
        # PA LLM（默认）
        client = create_llm_client()
        client = create_llm_client("pa", pa_model=PAModel.PA_JT_80B)

        # Mock 客户端
        client = create_llm_client("mock")

        # DeepSeek（OpenAI 兼容协议）
        os.environ["DEEPSEEK_API_KEY"] = "sk-xxx"
        client = create_llm_client("deepseek")

        # 自定义 headers/body
        from ark_agentic.core.llm import DynamicValues
        client = create_llm_client(
            "deepseek",
            api_key="sk-xxx",
            extra_headers={"x-trace-id": DynamicValues.uuid()},
            extra_body={"reqId": DynamicValues.uuid()},
        )
    """
    if provider == "pa":
        # PA Internal LLM
        return create_pa_client(model=pa_model, **kwargs)
    elif provider == "mock":
        # Mock LLM (for testing/demo, no API key required)
        config = LLMConfig(
            provider="mock",
            api_key="",
            base_url="",
            model=model or "mock-model",
            **kwargs,
        )
        return MockLLMClient(config)
    else:
        # OpenAI 兼容 API (deepseek)
        resolved_api_key = api_key

        # 尝试从环境变量读取
        if not resolved_api_key:
            env_key = ENV_KEYS.get(provider)
            if env_key:
                resolved_api_key = os.environ.get(env_key)

        if not resolved_api_key:
            raise ValueError(
                f"api_key is required. Either pass it directly or set {ENV_KEYS.get(provider, 'API_KEY')} environment variable."
            )

        config = LLMConfig(
            provider=provider,
            api_key=resolved_api_key,
            base_url=base_url or "",
            model=model or "",
            extra_headers=extra_headers or {},
            extra_body=extra_body or {},
            **kwargs,
        )
        return OpenAICompatibleClient(config)


def get_available_providers() -> list[str]:
    """获取可用的提供商列表"""
    return ["pa", "deepseek", "mock"]


def check_api_key_available(provider: str) -> bool:
    """检查 API Key 是否可用（从环境变量）"""
    if provider == "pa":
        # PA 需要检查对应的环境变量
        return bool(
            os.environ.get("PA_SX_BASE_URL") or os.environ.get("PA_JT_BASE_URL")
        )

    env_key = ENV_KEYS.get(provider)
    if not env_key:
        return False

    return bool(os.environ.get(env_key))
