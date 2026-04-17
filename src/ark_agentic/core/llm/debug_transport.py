"""
HTTP Debug Transport — 在 transport 层拦截 request/response（含 streaming chunks）。

插入位置：鉴权 Transport → **DebugTransport** → AsyncHTTPTransport
开关：环境变量 DEBUG_HTTP=1（唯一开关，专属 logger 自举，不依赖全局 LOG_LEVEL）
"""

from __future__ import annotations

import logging
import os
from typing import AsyncIterator

import httpx

_DEBUG_HTTP = os.getenv("DEBUG_HTTP", "").strip().lower() in ("1", "true", "yes")

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


def make_debug_client() -> httpx.AsyncClient:
    """构造带可选 debug 的 httpx.AsyncClient（无自定义 transport 时用）。"""
    return httpx.AsyncClient(
        transport=debug_transport(httpx.AsyncHTTPTransport(retries=3))
    )
