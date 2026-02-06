"""
OpenAI 兼容 LLM 客户端

支持 DeepSeek 等 OpenAI 兼容的 API。
"""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator

import httpx

from .base import BaseLLMClient, LLMConfig

logger = logging.getLogger(__name__)


def _resolve_extra_values(extra: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """解析额外参数，Callable 会被调用获取实际值

    Args:
        extra: 额外参数字典，值可以是静态值或 Callable
        context: 上下文字典（来自 chat() 的 kwargs）

    Returns:
        解析后的参数字典
    """
    resolved = {}
    for key, value in extra.items():
        resolved[key] = value(context) if callable(value) else value
    return resolved


# ============ Provider 配置 ============

PROVIDER_CONFIGS = {
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "default_model": "deepseek-chat",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o-mini",
    },
}


class OpenAICompatibleClient(BaseLLMClient):
    """OpenAI 兼容客户端

    支持所有 OpenAI 兼容的 API：
    - DeepSeek
    - OpenAI
    - 其他兼容服务
    """

    def __init__(self, config: LLMConfig) -> None:
        super().__init__(config)

        # 确定 base_url
        if config.base_url:
            self.base_url = config.base_url.rstrip("/")
        elif config.provider in PROVIDER_CONFIGS:
            self.base_url = PROVIDER_CONFIGS[config.provider]["base_url"]
        else:
            raise ValueError(f"Unknown provider: {config.provider}, please provide base_url")

        # 确定模型
        if config.model:
            self.model = config.model
        elif config.provider in PROVIDER_CONFIGS:
            self.model = PROVIDER_CONFIGS[config.provider]["default_model"]
        else:
            self.model = "gpt-4o-mini"

        # API Key
        if not config.api_key:
            raise ValueError("api_key is required")
        self.api_key = config.api_key

        # HTTP 客户端
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """获取或创建 HTTP 客户端"""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.config.timeout, connect=10.0),
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            )
        return self._client

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        stream: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any] | AsyncIterator[dict[str, Any]]:
        """发送聊天请求

        Args:
            messages: 消息列表
            tools: 工具定义列表
            stream: 是否流式输出
            **kwargs: 其他参数（也作为动态值的 context）

        Returns:
            非流式：完整响应字典
            流式：事件迭代器
        """
        # kwargs 作为 context 传递给动态值函数
        context = kwargs.copy()

        # 构建请求体
        body: dict[str, Any] = {
            "model": kwargs.get("model", self.model),
            "messages": messages,
            "temperature": kwargs.get("temperature", self.config.temperature),
            "max_tokens": kwargs.get("max_tokens", self.config.max_tokens),
            "stream": stream,
        }

        # 添加工具
        if tools:
            body["tools"] = tools
            body["tool_choice"] = kwargs.get("tool_choice", "auto")

        # 解析并合并额外 body（在 kwargs 之前，允许 extra_body 覆盖默认值）
        if self.config.extra_body:
            body.update(_resolve_extra_values(self.config.extra_body, context))

        # 移除已处理的 kwargs
        for key in ["model", "temperature", "max_tokens", "tool_choice"]:
            kwargs.pop(key, None)

        # 添加其他 kwargs（不覆盖 extra_body）
        for key, value in kwargs.items():
            if key not in body:
                body[key] = value

        # 解析额外 headers
        extra_headers = (
            _resolve_extra_values(self.config.extra_headers, context)
            if self.config.extra_headers
            else {}
        )

        url = f"{self.base_url}/chat/completions"

        if stream:
            return self._stream_chat(url, body, extra_headers)
        else:
            return await self._sync_chat(url, body, extra_headers)

    async def _sync_chat(
        self, url: str, body: dict[str, Any], extra_headers: dict[str, str] | None = None
    ) -> dict[str, Any]:
        """非流式请求"""
        client = await self._get_client()

        for attempt in range(self.config.max_retries):
            try:
                response = await client.post(url, json=body, headers=extra_headers)
                response.raise_for_status()
                return response.json()

            except httpx.HTTPStatusError as e:
                logger.error(f"HTTP error {e.response.status_code}: {e.response.text}")
                if attempt < self.config.max_retries - 1:
                    import asyncio
                    await asyncio.sleep(self.config.retry_delay * (attempt + 1))
                else:
                    raise

            except httpx.RequestError as e:
                logger.error(f"Request error: {e}")
                if attempt < self.config.max_retries - 1:
                    import asyncio
                    await asyncio.sleep(self.config.retry_delay * (attempt + 1))
                else:
                    raise

        raise RuntimeError("Max retries exceeded")

    async def _stream_chat(
        self, url: str, body: dict[str, Any], extra_headers: dict[str, str] | None = None
    ) -> AsyncIterator[dict[str, Any]]:
        """流式请求"""
        client = await self._get_client()

        async with client.stream("POST", url, json=body, headers=extra_headers) as response:
            response.raise_for_status()

            async for line in response.aiter_lines():
                if not line:
                    continue

                # SSE 格式：data: {...}
                if line.startswith("data: "):
                    data = line[6:]

                    if data == "[DONE]":
                        break

                    try:
                        yield json.loads(data)
                    except json.JSONDecodeError:
                        logger.warning(f"Failed to parse SSE data: {data}")

    async def close(self) -> None:
        """关闭客户端"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None


# ============ 便捷函数 ============


def create_deepseek_client(
    api_key: str,
    model: str = "deepseek-chat",
    **kwargs: Any,
) -> OpenAICompatibleClient:
    """创建 DeepSeek 客户端"""
    config = LLMConfig(
        provider="deepseek",
        api_key=api_key,
        model=model,
        **kwargs,
    )
    return OpenAICompatibleClient(config)


def create_openai_client(
    api_key: str,
    model: str = "gpt-4o-mini",
    **kwargs: Any,
) -> OpenAICompatibleClient:
    """创建 OpenAI 客户端"""
    config = LLMConfig(
        provider="openai",
        api_key=api_key,
        model=model,
        **kwargs,
    )
    return OpenAICompatibleClient(config)
