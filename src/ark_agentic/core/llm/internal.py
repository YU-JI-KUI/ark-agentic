"""
内部 API LLM 客户端

支持自定义的内部 LLM API。

包含两种客户端：
- InternalAPIClient: 内部 API 客户端（支持 trace headers）
- SimpleInternalClient: 简化内部 API 客户端（仅 messages + stream）
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, AsyncIterator

import httpx

from .base import BaseLLMClient, LLMConfig

logger = logging.getLogger(__name__)


class InternalAPIClient(BaseLLMClient):
    """内部 API 客户端

    支持自定义的内部 LLM API：
    - Headers:
        - Content-Type: application/json
        - Authorization: Bearer xxx
        - trace-appId: xxx (驼峰)
        - trace-source: xxx (可选)
        - trace-userId: xxx (可选)
    - Body:
        - reqId: uuid4 字符串
        - stream: boolean
        - messages: [{role, content}]
    - Response: OpenAI 兼容格式
    """

    def __init__(self, config: LLMConfig) -> None:
        super().__init__(config)

        if not config.base_url:
            raise ValueError("base_url is required for internal API")
        self.base_url = config.base_url.rstrip("/")

        if not config.authorization:
            raise ValueError("authorization is required for internal API")
        self.authorization = config.authorization

        if not config.trace_appid:
            raise ValueError("trace_appid is required for internal API")
        self.trace_appid = config.trace_appid

        # 可选参数
        self.trace_source = config.trace_source
        self.trace_user_id = config.trace_user_id

        # HTTP 客户端
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """获取或创建 HTTP 客户端"""
        if self._client is None or self._client.is_closed:
            headers = {
                "Content-Type": "application/json",
                "Authorization": self.authorization,
                "trace-appId": self.trace_appid,
            }
            if self.trace_source:
                headers["trace-source"] = self.trace_source
            if self.trace_user_id:
                headers["trace-userId"] = self.trace_user_id

            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.config.timeout, connect=10.0),
                headers=headers,
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
            tools: 工具定义列表（可能不支持，会尝试发送）
            stream: 是否流式输出
            **kwargs: 其他参数

        Returns:
            非流式：完整响应字典（OpenAI 兼容格式）
            流式：事件迭代器
        """
        # 保留完整的 OpenAI 消息格式（包括 tool_calls 和 tool role 消息）
        preserved_messages = self._preserve_messages(messages)

        # 构建请求体
        body: dict[str, Any] = {
            "reqId": str(uuid.uuid4()),
            "stream": stream,
            "messages": preserved_messages,
        }

        if tools:
            body["tools"] = tools

        if stream:
            return self._stream_chat(self.base_url, body)
        return await self._sync_chat(self.base_url, body)

    async def _sync_chat(self, url: str, body: dict[str, Any]) -> dict[str, Any]:
        """非流式请求"""
        client = await self._get_client()

        for attempt in range(self.config.max_retries):
            try:
                response = await client.post(url, json=body)
                response.raise_for_status()
                return self._normalize_response(response.json())
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
        self, url: str, body: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        """流式请求"""
        client = await self._get_client()

        async with client.stream("POST", url, json=body) as response:
            response.raise_for_status()

            async for line in response.aiter_lines():
                if not line:
                    continue

                if line.startswith("data: "):
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    try:
                        yield self._normalize_stream_chunk(json.loads(data))
                    except json.JSONDecodeError:
                        logger.warning(f"Failed to parse SSE data: {data}")
                else:
                    try:
                        yield self._normalize_stream_chunk(json.loads(line))
                    except json.JSONDecodeError:
                        pass

    @staticmethod
    def _preserve_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """保留完整消息结构，包括 tool_calls 和 tool role 消息。

        不再简化为 {role, content}，确保 ReAct 循环中的工具调用链完整传递给 LLM。
        """
        preserved: list[dict[str, Any]] = []
        for msg in messages:
            role = msg.get("role", "user")
            out: dict[str, Any] = {"role": role}

            if msg.get("content") is not None:
                out["content"] = msg["content"]

            # assistant 消息可能携带 tool_calls
            if role == "assistant" and msg.get("tool_calls"):
                out["tool_calls"] = msg["tool_calls"]
                # OpenAI 规范: assistant 有 tool_calls 时 content 可为 null
                if "content" not in out:
                    out["content"] = None

            # tool role 消息必须携带 tool_call_id
            if role == "tool":
                if msg.get("tool_call_id"):
                    out["tool_call_id"] = msg["tool_call_id"]
                # content 已在上面处理

            preserved.append(out)
        return preserved

    def _normalize_response(self, data: dict[str, Any]) -> dict[str, Any]:
        """将响应转换为 OpenAI 兼容格式"""
        if "choices" in data:
            return data

        content = data.get("content") or data.get("response") or data.get("text") or ""
        return {
            "id": data.get("id", f"internal-{uuid.uuid4().hex[:8]}"),
            "model": data.get("model", "internal"),
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": data.get("finish_reason", "stop"),
                }
            ],
            "usage": data.get("usage", {}),
        }

    def _normalize_stream_chunk(self, data: dict[str, Any]) -> dict[str, Any]:
        """将流式块转换为 OpenAI 兼容格式"""
        if "choices" in data:
            return data

        delta_content = data.get("delta") or data.get("content") or data.get("text") or ""
        return {
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": delta_content},
                    "finish_reason": data.get("finish_reason"),
                }
            ]
        }

    async def close(self) -> None:
        """关闭客户端"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None


class SimpleInternalClient(BaseLLMClient):
    """简化内部 API 客户端

    最简单的内部 LLM API 客户端：
    - Body: {messages: [{role, content}], stream: bool}
    - 支持流式和非流式输出
    - 返回 OpenAI 兼容格式
    """

    def __init__(self, config: LLMConfig) -> None:
        super().__init__(config)

        if not config.base_url:
            raise ValueError("base_url is required for simple internal API")
        self.base_url = config.base_url.rstrip("/")
        self.authorization = config.authorization

        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """获取或创建 HTTP 客户端"""
        if self._client is None or self._client.is_closed:
            headers = {"Content-Type": "application/json"}
            if self.authorization:
                headers["Authorization"] = self.authorization

            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.config.timeout, connect=10.0),
                headers=headers,
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
            tools: 工具定义列表（尝试传递，由后端决定是否支持）
            stream: 是否流式输出
            **kwargs: 其他参数

        Returns:
            非流式：完整响应字典（OpenAI 兼容格式）
            流式：事件迭代器
        """
        body: dict[str, Any] = {"messages": messages, "stream": stream}

        if tools:
            body["tools"] = tools

        if stream:
            return self._stream_chat(self.base_url, body)
        return await self._sync_chat(self.base_url, body)

    async def _sync_chat(self, url: str, body: dict[str, Any]) -> dict[str, Any]:
        """非流式请求"""
        client = await self._get_client()

        for attempt in range(self.config.max_retries):
            try:
                response = await client.post(url, json=body)
                response.raise_for_status()
                return self._normalize_response(response.json())
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
        self, url: str, body: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        """流式请求"""
        client = await self._get_client()

        async with client.stream("POST", url, json=body) as response:
            response.raise_for_status()

            async for line in response.aiter_lines():
                if not line:
                    continue

                if line.startswith("data: "):
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    try:
                        yield self._normalize_stream_chunk(json.loads(data))
                    except json.JSONDecodeError:
                        logger.warning(f"Failed to parse SSE data: {data}")
                else:
                    try:
                        yield self._normalize_stream_chunk(json.loads(line))
                    except json.JSONDecodeError:
                        pass

    def _normalize_response(self, data: dict[str, Any]) -> dict[str, Any]:
        """将响应转换为 OpenAI 兼容格式"""
        if "choices" in data:
            return data

        if isinstance(data, str):
            content = data
        else:
            content = data.get("content") or data.get("response") or data.get("text") or str(data)

        return {
            "id": f"simple-{uuid.uuid4().hex[:8]}",
            "model": "simple-internal",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": {},
        }

    def _normalize_stream_chunk(self, data: dict[str, Any]) -> dict[str, Any]:
        """将流式块转换为 OpenAI 兼容格式"""
        if "choices" in data:
            return data

        delta_content = data.get("delta") or data.get("content") or data.get("text") or ""
        return {
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": delta_content},
                    "finish_reason": data.get("finish_reason"),
                }
            ]
        }

    async def close(self) -> None:
        """关闭客户端"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None


# ============ 便捷函数 ============


def create_internal_client(
    base_url: str,
    authorization: str,
    trace_appid: str,
    trace_source: str = "",
    trace_user_id: str = "",
    **kwargs: Any,
) -> InternalAPIClient:
    """创建内部 API 客户端

    Args:
        base_url: API 端点 URL
        authorization: Authorization header 值
        trace_appid: trace-appId header 值
        trace_source: trace-source header 值（可选）
        trace_user_id: trace-userId header 值（可选）
        **kwargs: 其他配置参数

    Returns:
        内部 API 客户端
    """
    config = LLMConfig(
        provider="internal",
        base_url=base_url,
        authorization=authorization,
        trace_appid=trace_appid,
        trace_source=trace_source,
        trace_user_id=trace_user_id,
        **kwargs,
    )
    return InternalAPIClient(config)


def create_simple_client(
    base_url: str,
    authorization: str = "",
    **kwargs: Any,
) -> SimpleInternalClient:
    """创建简化内部 API 客户端

    Args:
        base_url: API 端点 URL
        authorization: Authorization header 值（可选）
        **kwargs: 其他配置参数

    Returns:
        简化内部 API 客户端
    """
    config = LLMConfig(
        provider="simple",
        base_url=base_url,
        authorization=authorization,
        **kwargs,
    )
    return SimpleInternalClient(config)
