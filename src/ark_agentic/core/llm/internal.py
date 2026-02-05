"""
内部 API LLM 客户端

支持自定义的内部 LLM API。

包含三种客户端：
- InternalAPIClient: 通用内部 API 客户端
- UnifiedInternalClient: 统一内部 API 客户端（特定 headers 和 body 格式）
- SimpleInternalClient: 简化内部 API 客户端（message -> content）
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

    支持自定义的内部 LLM API，特点：
    - 需要 Authorization header
    - 需要 trace-appid header
    - POST 请求
    - Body 只支持 stream 和 messages
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

        # HTTP 客户端
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """获取或创建 HTTP 客户端"""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.config.timeout, connect=10.0),
                headers={
                    "Authorization": self.authorization,
                    "trace-appid": self.trace_appid,
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

        内部 API 只支持基本参数：
        - stream: 是否流式
        - messages: 消息列表

        Args:
            messages: 消息列表
            tools: 工具定义列表（内部 API 可能不支持，会尝试发送）
            stream: 是否流式输出
            **kwargs: 其他参数（可能被忽略）

        Returns:
            非流式：完整响应字典
            流式：事件迭代器
        """
        # 简化消息格式，只保留 role 和 content
        simplified_messages = []
        for msg in messages:
            simplified_msg = {
                "role": msg.get("role", "user"),
                "content": msg.get("content", ""),
            }
            simplified_messages.append(simplified_msg)

        # 构建请求体（内部 API 只支持 stream 和 messages）
        body: dict[str, Any] = {
            "stream": stream,
            "messages": simplified_messages,
        }

        # 如果 API 支持工具，可以尝试添加
        if tools:
            body["tools"] = tools

        if stream:
            return self._stream_chat(self.base_url, body)
        else:
            return await self._sync_chat(self.base_url, body)

    async def _sync_chat(
        self, url: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        """非流式请求"""
        client = await self._get_client()

        for attempt in range(self.config.max_retries):
            try:
                response = await client.post(url, json=body)
                response.raise_for_status()
                data = response.json()

                # 转换为 OpenAI 兼容格式（如果需要）
                return self._normalize_response(data)

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

                # 尝试 SSE 格式
                if line.startswith("data: "):
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    try:
                        yield self._normalize_stream_chunk(json.loads(data))
                    except json.JSONDecodeError:
                        logger.warning(f"Failed to parse SSE data: {data}")
                else:
                    # 可能是纯 JSON 行
                    try:
                        yield self._normalize_stream_chunk(json.loads(line))
                    except json.JSONDecodeError:
                        pass

    def _normalize_response(self, data: dict[str, Any]) -> dict[str, Any]:
        """将内部 API 响应转换为 OpenAI 兼容格式"""
        # 如果已经是 OpenAI 格式，直接返回
        if "choices" in data:
            return data

        # 尝试转换常见格式
        content = data.get("content") or data.get("response") or data.get("text") or ""

        return {
            "id": data.get("id", "internal-response"),
            "model": data.get("model", "internal"),
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": content,
                    },
                    "finish_reason": data.get("finish_reason", "stop"),
                }
            ],
            "usage": data.get("usage", {}),
        }

    def _normalize_stream_chunk(self, data: dict[str, Any]) -> dict[str, Any]:
        """将内部 API 流式块转换为 OpenAI 兼容格式"""
        # 如果已经是 OpenAI 格式，直接返回
        if "choices" in data:
            return data

        # 尝试提取内容增量
        delta_content = (
            data.get("delta") or
            data.get("content") or
            data.get("text") or
            ""
        )

        return {
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "content": delta_content,
                    },
                    "finish_reason": data.get("finish_reason"),
                }
            ]
        }

    async def close(self) -> None:
        """关闭客户端"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None


class UnifiedInternalClient(BaseLLMClient):
    """统一内部 API 客户端

    支持特定格式的内部 LLM API：
    - URL: https://my-llm/api-app/agent/unified/v1/chat/completions
    - Headers:
        - Content-Type: application/json
        - Authorization: Bearer sk-xxxxx
        - trace-appId: xxx
        - trace-source: xxx (可选)
        - trace-userId: xxx (可选)
    - Body:
        - reqId: uuid4 字符串
        - stream: boolean
        - Messages: [{role, content}]
    - Response: OpenAI 兼容格式
    """

    def __init__(self, config: LLMConfig) -> None:
        super().__init__(config)

        if not config.base_url:
            raise ValueError("base_url is required for unified internal API")
        self.base_url = config.base_url.rstrip("/")

        if not config.authorization:
            raise ValueError("authorization is required for unified internal API")
        self.authorization = config.authorization

        if not config.trace_appid:
            raise ValueError("trace_appid is required for unified internal API")
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
            # 添加可选 headers
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
            tools: 工具定义列表（此 API 不支持，会被忽略）
            stream: 是否流式输出
            **kwargs: 其他参数

        Returns:
            非流式：完整响应字典（OpenAI 兼容格式）
            流式：事件迭代器
        """
        # 简化消息格式
        simplified_messages = []
        for msg in messages:
            simplified_messages.append({
                "role": msg.get("role", "user"),
                "content": msg.get("content", ""),
            })

        # 构建请求体（使用 Messages 而非 messages）
        body: dict[str, Any] = {
            "reqId": str(uuid.uuid4()),
            "stream": stream,
            "Messages": simplified_messages,
        }

        if stream:
            return self._stream_chat(self.base_url, body)
        else:
            return await self._sync_chat(self.base_url, body)

    async def _sync_chat(
        self, url: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        """非流式请求"""
        client = await self._get_client()

        for attempt in range(self.config.max_retries):
            try:
                response = await client.post(url, json=body)
                response.raise_for_status()
                data = response.json()

                # 转换为 OpenAI 兼容格式
                return self._normalize_response(data)

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
        # 如果已经是 OpenAI 格式，直接返回
        if "choices" in data:
            return data

        # 尝试从不同字段提取内容
        content = data.get("content") or data.get("response") or data.get("text") or ""

        return {
            "id": data.get("id", f"unified-{uuid.uuid4().hex[:8]}"),
            "model": data.get("model", "unified-internal"),
            "choices": [
                {
                    "index": data.get("index", 0),
                    "message": {
                        "role": "assistant",
                        "content": content,
                    },
                    "finish_reason": data.get("finish_reason", "stop"),
                }
            ],
            "usage": data.get("usage", {}),
        }

    def _normalize_stream_chunk(self, data: dict[str, Any]) -> dict[str, Any]:
        """将流式块转换为 OpenAI 兼容格式"""
        if "choices" in data:
            return data

        delta_content = (
            data.get("delta") or
            data.get("content") or
            data.get("text") or
            ""
        )

        return {
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "content": delta_content,
                    },
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

    支持最简单的内部 LLM API：
    - 输入: 单个消息字符串
    - 输出: 内容字符串
    - 自动转换为 OpenAI 兼容格式

    适用于已封装好的工具类 API，参数是 message，返回是 content。
    """

    def __init__(self, config: LLMConfig) -> None:
        super().__init__(config)

        if not config.base_url:
            raise ValueError("base_url is required for simple internal API")
        self.base_url = config.base_url.rstrip("/")

        # 可选的认证
        self.authorization = config.authorization

        # HTTP 客户端
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

        将多轮消息合并为单个 message 发送。

        Args:
            messages: 消息列表
            tools: 工具定义列表（不支持，会被忽略）
            stream: 是否流式输出（此 API 不支持流式，会被忽略）
            **kwargs: 其他参数

        Returns:
            完整响应字典（OpenAI 兼容格式）
        """
        # 合并所有消息为单个字符串
        combined_message = self._combine_messages(messages)

        # 构建请求体
        body: dict[str, Any] = {
            "message": combined_message,
        }

        # 此 API 不支持流式，始终返回完整响应
        return await self._sync_chat(self.base_url, body)

    def _combine_messages(self, messages: list[dict[str, Any]]) -> str:
        """将多轮消息合并为单个字符串"""
        parts = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                parts.append(f"[System]: {content}")
            elif role == "user":
                parts.append(f"[User]: {content}")
            elif role == "assistant":
                parts.append(f"[Assistant]: {content}")
        return "\n".join(parts) if len(parts) > 1 else (parts[0].split(": ", 1)[1] if parts else "")

    async def _sync_chat(
        self, url: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        """非流式请求"""
        client = await self._get_client()

        for attempt in range(self.config.max_retries):
            try:
                response = await client.post(url, json=body)
                response.raise_for_status()
                data = response.json()

                # 转换为 OpenAI 兼容格式
                return self._normalize_response(data)

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

    def _normalize_response(self, data: dict[str, Any]) -> dict[str, Any]:
        """将响应转换为 OpenAI 兼容格式"""
        # 如果已经是 OpenAI 格式，直接返回
        if "choices" in data:
            return data

        # 简单 API 可能直接返回字符串或 {content: "..."}
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
                    "message": {
                        "role": "assistant",
                        "content": content,
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {},
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
    **kwargs: Any,
) -> InternalAPIClient:
    """创建内部 API 客户端

    Args:
        base_url: API 端点 URL
        authorization: Authorization header 值
        trace_appid: trace-appid header 值
        **kwargs: 其他配置参数

    Returns:
        内部 API 客户端
    """
    config = LLMConfig(
        provider="internal",
        base_url=base_url,
        authorization=authorization,
        trace_appid=trace_appid,
        **kwargs,
    )
    return InternalAPIClient(config)


def create_unified_client(
    base_url: str,
    authorization: str,
    trace_appid: str,
    trace_source: str = "",
    trace_user_id: str = "",
    **kwargs: Any,
) -> UnifiedInternalClient:
    """创建统一内部 API 客户端

    Args:
        base_url: API 端点 URL (e.g., https://my-llm/api-app/agent/unified/v1/chat/completions)
        authorization: Authorization header 值 (e.g., Bearer sk-xxxxx)
        trace_appid: trace-appId header 值
        trace_source: trace-source header 值（可选）
        trace_user_id: trace-userId header 值（可选）
        **kwargs: 其他配置参数

    Returns:
        统一内部 API 客户端
    """
    config = LLMConfig(
        provider="unified",
        base_url=base_url,
        authorization=authorization,
        trace_appid=trace_appid,
        trace_source=trace_source,
        trace_user_id=trace_user_id,
        **kwargs,
    )
    return UnifiedInternalClient(config)


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
