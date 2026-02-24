"""
PA-SX LLM：Trace Header + Body 注入 Transport + ChatOpenAI 构建。

Header 与 Body 注入全部在本模块的 Transport 内完成；Bearer 由 ChatOpenAI(api_key=...) 注入。
"""

from __future__ import annotations

import json as _json
import logging
import uuid
from typing import Any, TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from langchain_core.language_models.chat_models import BaseChatModel
    from .factory import PAModelConfig

logger = logging.getLogger(__name__)


def _merge_body(content: bytes, fields: dict[str, Any]) -> bytes:
    """将 fields 合并进 JSON body；已存在的 key 不覆盖。"""
    if not content:
        return _json.dumps(fields).encode()
    try:
        body = _json.loads(content)
    except (ValueError, _json.JSONDecodeError):
        return content
    injected = {k: v for k, v in fields.items() if k not in body}
    if not injected:
        return content
    body.update(injected)
    return _json.dumps(body).encode()


def _rebuild_request(
    request: httpx.Request,
    extra_headers: dict[str, str],
    new_content: bytes,
) -> httpx.Request:
    """基于原请求构造新 Request，合并 headers 并替换 body。"""
    merged = dict(request.headers)
    merged.update(extra_headers)
    return httpx.Request(
        method=request.method,
        url=request.url,
        headers=merged,
        content=new_content,
        extensions=request.extensions,
    )


# ============ SX Transport ============


class PASXTraceTransport(httpx.AsyncBaseTransport):
    """httpx 异步 Transport：为 PA-SX 请求注入 trace Header 与 PA Body 字段。"""

    def __init__(
        self,
        *,
        base_transport: httpx.AsyncBaseTransport | None = None,
        trace_app_id: str = "",
        trace_source: str = "",
        trace_user_id: str = "",
        enable_thinking: bool = False,
        extra_body: dict[str, Any] | None = None,
    ) -> None:
        self._transport = base_transport or httpx.AsyncHTTPTransport(retries=3)
        self._trace_app_id = trace_app_id
        self._trace_source = trace_source
        self._trace_user_id = trace_user_id
        self._enable_thinking = enable_thinking
        self._extra_body = extra_body or {}

    def _build_trace_headers(self) -> dict[str, str]:
        return {
            "trace-appId": self._trace_app_id,
            "trace-source": self._trace_source,
            "trace-userId": self._trace_user_id,
        }

    def _build_body_fields(self, request_id: str) -> dict[str, Any]:
        defaults: dict[str, Any] = {
            "request_id": request_id,
            "seed": 42,
            "chat_template_kwargs": {
                "enable_thinking": self._enable_thinking,
                "thinking": self._enable_thinking,
            },
        }
        return {**defaults, **self._extra_body}

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        request_id = uuid.uuid4().hex
        trace_headers = self._build_trace_headers()
        body_fields = self._build_body_fields(request_id)
        new_content = _merge_body(request.content, body_fields)
        new_request = _rebuild_request(request, trace_headers, new_content)
        return await self._transport.handle_async_request(new_request)


# ============ Builder ============


def create_pa_sx_llm(
    config: "PAModelConfig",
    *,
    temperature: float,
    max_tokens: int,
    streaming: bool,
    enable_thinking: bool = False,
    extra_body_override: dict[str, Any] | None = None,
) -> "BaseChatModel":
    """构建 PA-SX 系列 ChatOpenAI。"""
    from langchain_openai import ChatOpenAI

    transport = PASXTraceTransport(
        base_transport=httpx.AsyncHTTPTransport(retries=3),
        trace_app_id=config.trace_app_id,
        enable_thinking=enable_thinking,
        extra_body=extra_body_override,
    )
    http_client = httpx.AsyncClient(transport=transport)
    logger.info(f"PA-SX model {config.model_name} with trace transport")

    return ChatOpenAI(
        base_url=config.base_url,
        api_key=config.api_key or "EMPTY",
        model=config.model_name,
        temperature=temperature,
        max_tokens=max_tokens,
        streaming=streaming,
        http_async_client=http_client,
    )
