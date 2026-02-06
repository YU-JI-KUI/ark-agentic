"""
PA Internal LLM 客户端

支持 PA 内部 LLM API，包含三个模型：
- PA-JT-80B: JT 系列，需要 RSA 签名和 App 签名
- PA-SX-80B: SX 系列，使用 trace headers
- PA-SX-235B: SX 系列，使用 trace headers

所有模型使用 OpenAI 兼容方式调用。
"""

from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Literal

from .base import DynamicValues, LLMConfig
from .openai_compat import OpenAICompatibleClient


# ============ 签名函数占位符 ============


def get_sign(rsa_private_key: str, request_time: str) -> str:
    """RSA 签名（占位符）

    Args:
        rsa_private_key: RSA 私钥
        request_time: 请求时间戳（毫秒）

    Returns:
        签名字符串
    """
    # TODO: 实现 RSA 签名逻辑
    return ""


def generate_app_sign(app_key: str, app_secret: str, request_time: str) -> str:
    """App 签名（占位符）

    Args:
        app_key: App Key
        app_secret: App Secret
        request_time: 请求时间戳（毫秒）

    Returns:
        签名字符串
    """
    # TODO: 实现 App 签名逻辑
    return ""


# ============ 模型枚举 ============


class PAModel(str, Enum):
    """PA 模型枚举"""

    PA_JT_80B = "PA-JT-80B"
    PA_SX_80B = "PA-SX-80B"
    PA_SX_235B = "PA-SX-235B"


# ============ 模型配置 ============


@dataclass
class PAModelConfig:
    """PA 模型配置"""

    base_url: str
    model_name: str
    trace_app_id: str
    model_type: Literal["jt", "sx"]


def _get_model_configs() -> dict[PAModel, PAModelConfig]:
    """获取模型配置（延迟读取环境变量）"""
    return {
        PAModel.PA_JT_80B: PAModelConfig(
            base_url=os.getenv("PA_JT_BASE_URL", ""),
            model_name="PA-JT-80B",
            trace_app_id="",
            model_type="jt",
        ),
        PAModel.PA_SX_80B: PAModelConfig(
            base_url=os.getenv("PA_SX_BASE_URL", ""),
            model_name="PA-SX-80B",
            trace_app_id=os.getenv("PA_SX_80B_APP_ID", ""),
            model_type="sx",
        ),
        PAModel.PA_SX_235B: PAModelConfig(
            base_url=os.getenv("PA_SX_BASE_URL", ""),
            model_name="PA-SX-235B",
            trace_app_id=os.getenv("PA_SX_235B_APP_ID", ""),
            model_type="sx",
        ),
    }


# ============ Headers/Body 构建器 ============


def _build_jt_headers_fn() -> Callable[[dict[str, Any]], dict[str, str]]:
    """返回 JT 系列 headers 构建函数"""

    def build(ctx: dict[str, Any]) -> dict[str, str]:
        request_time = str(int(time.time() * 1000))
        app_key = os.getenv("PA_JT_GPT_APP_KEY", "")
        app_secret = os.getenv("PA_JT_GPT_APP_SECRET", "")
        rsa_pk = os.getenv("PA_JT_RSA_PRIVATE_KEY", "")

        return {
            "openAPICode": os.getenv("PA_JT_OPEN_API_CODE", ""),
            "openAPICredential": os.getenv("PA_JT_OPEN_API_CREDENTIAL", ""),
            "openAPIRequestTime": request_time,
            "openAPISignature": get_sign(rsa_pk, request_time),
            "gpt_app_key": app_key,
            "gpt_signature": generate_app_sign(app_key, app_secret, request_time),
        }

    return build


def _build_jt_extra_body() -> dict[str, Any]:
    """构建 JT 系列 extra body"""
    return {
        "request_id": DynamicValues.uuid(),
        "scene_id": os.getenv("PA_JT_SCENE_ID", ""),
        "seed": 42,
        "chat_template_kwargs": DynamicValues.from_kwargs(
            "chat_template_kwargs", {"enable_thinking": False, "thinking": False}
        ),
    }


def _build_sx_headers(config: PAModelConfig) -> dict[str, str]:
    """构建 SX 系列 headers（静态）"""
    return {
        "Authorization": f"Bearer {os.getenv('PA_SX_API_KEY', '')}",
        "trace-appId": config.trace_app_id,
        "trace-source": "",
        "trace-userId": "",
    }


# ============ PA Internal Client ============


class PAInternalClient(OpenAICompatibleClient):
    """PA Internal LLM 客户端

    支持 PA-JT-80B、PA-SX-80B、PA-SX-235B 三个模型，
    使用 OpenAI 兼容方式调用。

    Examples:
        # 使用默认模型
        client = PAInternalClient(PAModel.PA_SX_80B)

        # 调用
        response = await client.chat(
            messages=[{"role": "user", "content": "你好"}],
        )

        # 使用 thinking 模式（仅 JT 系列）
        response = await client.chat(
            messages=[{"role": "user", "content": "你好"}],
            chat_template_kwargs={"enable_thinking": True, "thinking": True},
        )
    """

    def __init__(
        self,
        model: PAModel | str = PAModel.PA_SX_80B,
        **kwargs: Any,
    ) -> None:
        # 解析模型
        if isinstance(model, str):
            try:
                model = PAModel(model)
            except ValueError:
                raise ValueError(
                    f"Unknown PA model: {model}. "
                    f"Available: {[m.value for m in PAModel]}"
                )

        self.pa_model = model
        model_configs = _get_model_configs()
        self.model_config = model_configs[model]

        if not self.model_config.base_url:
            env_var = (
                "PA_JT_BASE_URL"
                if self.model_config.model_type == "jt"
                else "PA_SX_BASE_URL"
            )
            raise ValueError(f"{env_var} environment variable is required")

        # 构建 extra_headers 和 extra_body
        if self.model_config.model_type == "jt":
            extra_headers: dict[str, Any] = {"_jt_headers": _build_jt_headers_fn()}
            extra_body = _build_jt_extra_body()
        else:
            extra_headers = _build_sx_headers(self.model_config)
            extra_body = {}

        # 构建 LLMConfig
        config = LLMConfig(
            provider="pa",
            api_key="dummy",  # JT/SX 使用自定义认证
            base_url=self.model_config.base_url,
            model=self.model_config.model_name,
            extra_headers=extra_headers,
            extra_body=extra_body,
            **kwargs,
        )

        super().__init__(config)

    async def _get_client(self):
        """获取或创建 HTTP 客户端（不设置默认 Authorization）"""
        import httpx

        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.config.timeout, connect=10.0),
                headers={"Content-Type": "application/json"},
            )
        return self._client

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        stream: bool = False,
        **kwargs: Any,
    ):
        """发送聊天请求

        Args:
            messages: 消息列表
            tools: 工具定义列表
            stream: 是否流式输出
            **kwargs: 其他参数

        Returns:
            非流式：完整响应字典
            流式：事件迭代器
        """
        # 处理 JT 系列的动态 headers
        if self.model_config.model_type == "jt":
            # 调用 _jt_headers 函数获取实际 headers
            jt_headers_fn = self.config.extra_headers.get("_jt_headers")
            if callable(jt_headers_fn):
                context = kwargs.copy()
                actual_headers = jt_headers_fn(context)
                # 临时替换 extra_headers
                original_extra_headers = self.config.extra_headers
                self.config.extra_headers = actual_headers
                try:
                    return await super().chat(messages, tools, stream, **kwargs)
                finally:
                    self.config.extra_headers = original_extra_headers

        return await super().chat(messages, tools, stream, **kwargs)


# ============ 便捷函数 ============


def create_pa_client(
    model: PAModel | str = PAModel.PA_SX_80B,
    **kwargs: Any,
) -> PAInternalClient:
    """创建 PA Internal LLM 客户端

    Args:
        model: 模型选择，可选 PA-JT-80B, PA-SX-80B, PA-SX-235B
        **kwargs: 其他配置参数

    Returns:
        PA Internal LLM 客户端

    Examples:
        # 使用默认模型
        client = create_pa_client()

        # 指定模型
        client = create_pa_client(PAModel.PA_JT_80B)
        client = create_pa_client("PA-SX-235B")
    """
    return PAInternalClient(model=model, **kwargs)
