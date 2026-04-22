"""
HTTP Debug Transport — 在 transport 层拦截 request/response（含 streaming chunks）。

插入位置：鉴权 Transport → URL Rewrite Transport → **DebugTransport** → HTTPTransport
开关：环境变量 DEBUG_HTTP=1（唯一开关，专属 logger 自举，不依赖全局 LOG_LEVEL）
"""

from __future__ import annotations

import logging
import os
from typing import AsyncIterator
from urllib.parse import urlsplit

import httpx

_DEBUG_HTTP = os.getenv("DEBUG_HTTP", "").strip().lower() in ("1", "true", "yes")
_CHAT_COMPLETIONS_PATH = "/chat/completions"

_logger = logging.getLogger("ark_agentic.http_debug")

if _DEBUG_HTTP:
    _logger.setLevel(logging.DEBUG)
    if not _logger.handlers:
        _handler = logging.StreamHandler()
        _handler.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%H:%M:%S"))
        _logger.addHandler(_handler)
        _logger.propagate = False


class _LoggingStream(httpx.AsyncByteStream):
    """包装响应流，实时打印每个 chunk（SSE event）。"""

    def __init__(self, inner: httpx.AsyncByteStream, url: str) -> None:
        self._inner = inner
        self._url = url
        self._chunks = 0
        self._bytes = 0

    async def __aiter__(self) -> AsyncIterator[bytes]:
        async for chunk in self._inner:
            self._chunks += 1
            self._bytes += len(chunk)
            text = chunk.decode("utf-8", errors="replace").rstrip("\n")
            for line in text.split("\n"):
                if line.strip():
                    _logger.debug("[HTTP_DEBUG] chunk | %s", line)
            yield chunk
        _logger.debug(
            "[HTTP_DEBUG] <<< stream done | %d chunks | %dB | %s",
            self._chunks,
            self._bytes,
            self._url,
        )

    async def aclose(self) -> None:
        await self._inner.aclose()


class _SyncLoggingStream(httpx.SyncByteStream):
    """包装同步响应流，实时打印每个 chunk。"""

    def __init__(self, inner: httpx.SyncByteStream, url: str) -> None:
        self._inner = inner
        self._url = url
        self._chunks = 0
        self._bytes = 0

    def __iter__(self):
        for chunk in self._inner:
            self._chunks += 1
            self._bytes += len(chunk)
            text = chunk.decode("utf-8", errors="replace").rstrip("\n")
            for line in text.split("\n"):
                if line.strip():
                    _logger.debug("[HTTP_DEBUG] chunk | %s", line)
            yield chunk
        _logger.debug(
            "[HTTP_DEBUG] <<< stream done | %d chunks | %dB | %s",
            self._chunks,
            self._bytes,
            self._url,
        )

    def close(self) -> None:
        self._inner.close()


def _should_rewrite_chat_completions(request: httpx.Request) -> bool:
    return (
        request.method.upper() == "POST"
        and request.url.path.endswith(_CHAT_COMPLETIONS_PATH)
    )


def _rewrite_request_url(request: httpx.Request, full_url: str) -> None:
    original_url = str(request.url)
    request.url = httpx.URL(full_url)
    _logger.debug(
        "[HTTP_DEBUG] rewrite url | %s -> %s",
        original_url,
        request.url,
    )


def derive_base_url_for_full_url(full_url: str) -> str:
    """从完整请求 URL 推导一个占位 base_url，供 OpenAI SDK 初始化。"""
    parts = urlsplit(full_url)
    if not parts.scheme or not parts.netloc:
        raise ValueError(
            "LLM_BASE_URL must be an absolute URL when LLM_BASE_URL_IS_FULL_URL=true."
        )
    return f"{parts.scheme}://{parts.netloc}/"


class RewriteURLTransport(httpx.BaseTransport):
    """在同步 transport 层把 chat/completions 请求改写为完整 URL。"""

    def __init__(self, inner: httpx.BaseTransport, full_url: str) -> None:
        self._inner = inner
        self._full_url = full_url

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if _should_rewrite_chat_completions(request):
            _rewrite_request_url(request, self._full_url)
        return self._inner.handle_request(request)


class RewriteURLAsyncTransport(httpx.AsyncBaseTransport):
    """在异步 transport 层把 chat/completions 请求改写为完整 URL。"""

    def __init__(self, inner: httpx.AsyncBaseTransport, full_url: str) -> None:
        self._inner = inner
        self._full_url = full_url

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if _should_rewrite_chat_completions(request):
            _rewrite_request_url(request, self._full_url)
        return await self._inner.handle_async_request(request)


class SyncDebugTransport(httpx.BaseTransport):
    """装饰器 Transport：打印同步 request/response。"""

    def __init__(self, inner: httpx.BaseTransport) -> None:
        self._inner = inner

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        body = request.content.decode("utf-8", errors="replace") if request.content else ""
        _logger.debug(
            "[HTTP_DEBUG] >>> %s %s\n  Headers: %s\n  Body: %s",
            request.method,
            request.url,
            dict(request.headers),
            body,
        )

        try:
            response = self._inner.handle_request(request)
        except Exception as exc:
            _logger.debug("[HTTP_DEBUG] !!! %s %s → %s", request.method, request.url, exc)
            raise

        _logger.debug(
            "[HTTP_DEBUG] <<< %d %s\n  Headers: %s",
            response.status_code,
            request.url,
            dict(response.headers),
        )

        response.stream = _SyncLoggingStream(response.stream, str(request.url))  # type: ignore[arg-type]
        return response


class DebugTransport(httpx.AsyncBaseTransport):
    """装饰器 Transport：打印 request headers/body + response status/headers + streaming chunks。"""

    def __init__(self, inner: httpx.AsyncBaseTransport) -> None:
        self._inner = inner

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        body = request.content.decode("utf-8", errors="replace") if request.content else ""
        _logger.debug(
            "[HTTP_DEBUG] >>> %s %s\n  Headers: %s\n  Body: %s",
            request.method,
            request.url,
            dict(request.headers),
            body,
        )

        try:
            response = await self._inner.handle_async_request(request)
        except Exception as exc:
            _logger.debug("[HTTP_DEBUG] !!! %s %s → %s", request.method, request.url, exc)
            raise

        _logger.debug(
            "[HTTP_DEBUG] <<< %d %s\n  Headers: %s",
            response.status_code,
            request.url,
            dict(response.headers),
        )

        response.stream = _LoggingStream(response.stream, str(request.url))  # type: ignore[arg-type]
        return response


def debug_transport(
    transport: httpx.AsyncBaseTransport,
) -> httpx.AsyncBaseTransport:
    """DEBUG_HTTP=1 时包装，否则原样返回。"""
    if _DEBUG_HTTP:
        return DebugTransport(transport)
    return transport


def debug_sync_transport(transport: httpx.BaseTransport) -> httpx.BaseTransport:
    """DEBUG_HTTP=1 时包装同步 transport，否则原样返回。"""
    if _DEBUG_HTTP:
        return SyncDebugTransport(transport)
    return transport


def make_debug_client(full_url: str | None = None) -> httpx.AsyncClient:
    """构造带可选 URL 改写和 debug 的 httpx.AsyncClient。"""
    transport: httpx.AsyncBaseTransport = httpx.AsyncHTTPTransport(retries=3)
    if full_url:
        transport = RewriteURLAsyncTransport(transport, full_url)
    return httpx.AsyncClient(transport=debug_transport(transport))


def make_debug_sync_client(full_url: str | None = None) -> httpx.Client:
    """构造带可选 URL 改写和 debug 的 httpx.Client。"""
    transport: httpx.BaseTransport = httpx.HTTPTransport(retries=3)
    if full_url:
        transport = RewriteURLTransport(transport, full_url)
    return httpx.Client(transport=debug_sync_transport(transport))
