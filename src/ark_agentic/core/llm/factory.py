"""
LLM Client 工厂

提供统一的客户端创建接口。
"""

from __future__ import annotations

import os
from typing import Any, Literal

from .base import LLMClientProtocol, LLMConfig
from .internal import InternalAPIClient, SimpleInternalClient
from .openai_compat import OpenAICompatibleClient
from .pa_internal_llm import PAModel, create_pa_client


# ============ 环境变量名 ============

ENV_KEYS = {
    "deepseek": "DEEPSEEK_API_KEY",
    "openai": "OPENAI_API_KEY",
}


def create_llm_client(
    provider: Literal["deepseek", "openai", "internal", "simple", "pa"] = "pa",
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    # PA 专用参数
    pa_model: str | PAModel = PAModel.PA_SX_80B,
    # 内部 API 专用参数
    authorization: str | None = None,
    trace_appid: str | None = None,
    trace_source: str | None = None,
    trace_user_id: str | None = None,
    # 扩展参数（用于 OpenAI 兼容 API 添加自定义 headers/body）
    extra_headers: dict[str, Any] | None = None,
    extra_body: dict[str, Any] | None = None,
    # 其他配置
    **kwargs: Any,
) -> LLMClientProtocol:
    """创建 LLM 客户端

    根据 provider 创建相应的客户端实例。

    Args:
        provider: 提供商，可选 "pa", "deepseek", "openai", "internal", "simple"
        api_key: API Key（如不提供，会尝试从环境变量读取）
        base_url: API 端点（可选，大多数情况下使用默认值）
        model: 模型名称（可选，使用默认模型）
        pa_model: PA 模型选择，可选 PA-JT-80B, PA-SX-80B, PA-SX-235B
        authorization: 内部 API 的 Authorization header
        trace_appid: 内部 API 的 trace-appId header
        trace_source: 内部 API 的 trace-source header（可选）
        trace_user_id: 内部 API 的 trace-userId header（可选）
        extra_headers: 额外 HTTP headers（值可以是静态值或 Callable 动态值）
        extra_body: 额外 body 参数（值可以是静态值或 Callable 动态值）
        **kwargs: 其他配置参数

    Returns:
        LLM 客户端实例

    Examples:
        # 使用 PA 内部 LLM（默认）
        client = create_llm_client()

        # 指定 PA 模型
        client = create_llm_client("pa", pa_model=PAModel.PA_JT_80B)

        # 使用带额外参数的 OpenAI 兼容 API
        from ark_agentic.core.llm import DynamicValues
        client = create_llm_client(
            "openai",
            api_key="sk-xxx",
            base_url="https://custom-api.example.com/v1",
            extra_headers={
                "trace-appId": "my-app",
                "trace-requestId": DynamicValues.uuid(),
                "trace-userId": DynamicValues.from_kwargs("user_id"),
            },
            extra_body={
                "reqId": DynamicValues.uuid(),
            },
        )

        # 从环境变量读取 API Key
        os.environ["DEEPSEEK_API_KEY"] = "sk-xxx"
        client = create_llm_client("deepseek")
    """
    if provider == "pa":
        # PA Internal LLM
        return create_pa_client(model=pa_model, **kwargs)
    else:
        # OpenAI 兼容 API (deepseek, openai)
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
    return ["pa", "deepseek", "openai", "internal", "simple"]


def check_api_key_available(provider: str) -> bool:
    """检查 API Key 是否可用（从环境变量）"""
    if provider in ("internal", "simple"):
        return False  # 内部 API 需要显式配置

    if provider == "pa":
        # PA 需要检查对应的环境变量
        return bool(
            os.environ.get("PA_SX_BASE_URL") or os.environ.get("PA_JT_BASE_URL")
        )

    env_key = ENV_KEYS.get(provider)
    if not env_key:
        return False

    return bool(os.environ.get(env_key))
