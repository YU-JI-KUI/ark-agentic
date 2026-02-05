"""
LLM Client 工厂

提供统一的客户端创建接口。
"""

from __future__ import annotations

import os
from typing import Any, Literal

from .base import LLMClientProtocol, LLMConfig
from .internal import InternalAPIClient
from .openai_compat import OpenAICompatibleClient


# ============ 环境变量名 ============

ENV_KEYS = {
    "deepseek": "DEEPSEEK_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "openai": "OPENAI_API_KEY",
}


def create_llm_client(
    provider: Literal["deepseek", "gemini", "openai", "internal"] = "deepseek",
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    # 内部 API 专用参数
    authorization: str | None = None,
    trace_appid: str | None = None,
    # 其他配置
    **kwargs: Any,
) -> LLMClientProtocol:
    """创建 LLM 客户端

    根据 provider 创建相应的客户端实例。

    Args:
        provider: 提供商，可选 "deepseek", "gemini", "openai", "internal"
        api_key: API Key（如不提供，会尝试从环境变量读取）
        base_url: API 端点（可选，大多数情况下使用默认值）
        model: 模型名称（可选，使用默认模型）
        authorization: 内部 API 的 Authorization header
        trace_appid: 内部 API 的 trace-appid header
        **kwargs: 其他配置参数

    Returns:
        LLM 客户端实例

    Examples:
        # 使用 DeepSeek
        client = create_llm_client("deepseek", api_key="sk-xxx")

        # 使用 Gemini
        client = create_llm_client("gemini", api_key="xxx")

        # 使用内部 API
        client = create_llm_client(
            "internal",
            base_url="http://internal-api.example.com/chat",
            authorization="Bearer xxx",
            trace_appid="my-app",
        )

        # 从环境变量读取 API Key
        os.environ["DEEPSEEK_API_KEY"] = "sk-xxx"
        client = create_llm_client("deepseek")
    """
    if provider == "internal":
        # 内部 API
        if not base_url:
            raise ValueError("base_url is required for internal provider")
        if not authorization:
            raise ValueError("authorization is required for internal provider")
        if not trace_appid:
            raise ValueError("trace_appid is required for internal provider")

        config = LLMConfig(
            provider="internal",
            base_url=base_url,
            authorization=authorization,
            trace_appid=trace_appid,
            model=model or "",
            **kwargs,
        )
        return InternalAPIClient(config)

    else:
        # OpenAI 兼容 API
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
            **kwargs,
        )
        return OpenAICompatibleClient(config)


def get_available_providers() -> list[str]:
    """获取可用的提供商列表"""
    return ["deepseek", "gemini", "openai", "internal"]


def check_api_key_available(provider: str) -> bool:
    """检查 API Key 是否可用（从环境变量）"""
    if provider == "internal":
        return False  # 内部 API 需要显式配置

    env_key = ENV_KEYS.get(provider)
    if not env_key:
        return False

    return bool(os.environ.get(env_key))
