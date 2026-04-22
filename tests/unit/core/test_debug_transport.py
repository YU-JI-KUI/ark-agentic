"""Unit tests for debug_transport module."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakeStream(httpx.AsyncByteStream):
    """Yields pre-defined chunks then closes."""

    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    async def __aiter__(self):
        for c in self._chunks:
            yield c

    async def aclose(self) -> None:
        pass


class _FakeSyncStream(httpx.SyncByteStream):
    """Yields pre-defined chunks then closes."""

    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    def __iter__(self):
        yield from self._chunks

    def close(self) -> None:
        pass


def _make_request(
    method: str = "POST",
    url: str = "https://gw.example.com/v1/chat/completions",
    body: bytes = b'{"model":"test"}',
) -> httpx.Request:
    return httpx.Request(method, url, content=body)


def _make_sync_request(
    method: str = "POST",
    url: str = "https://gw.example.com/v1/chat/completions",
    body: bytes = b'{"model":"test"}',
) -> httpx.Request:
    return httpx.Request(method, url, content=body)


class _OKTransport(httpx.AsyncBaseTransport):
    """Always returns a 200 with the given stream."""

    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=200,
            headers={"content-type": "text/event-stream"},
            stream=_FakeStream(self._chunks),
        )


class _ErrorTransport(httpx.AsyncBaseTransport):
    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        raise ConnectionError("connect timeout")


class _SyncOKTransport(httpx.BaseTransport):
    """Always returns a 200 with the given stream."""

    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=200,
            headers={"content-type": "text/event-stream"},
            stream=_FakeSyncStream(self._chunks),
        )


# ---------------------------------------------------------------------------
# Tests: debug_transport() switch
# ---------------------------------------------------------------------------

def test_debug_transport_off_returns_original(monkeypatch: pytest.MonkeyPatch) -> None:
    """DEBUG_HTTP unset → debug_transport() returns the transport as-is."""
    monkeypatch.delenv("DEBUG_HTTP", raising=False)

    # Re-import to pick up patched env
    import importlib
    import ark_agentic.core.llm.debug_transport as mod
    importlib.reload(mod)

    inner = MagicMock(spec=httpx.AsyncBaseTransport)
    result = mod.debug_transport(inner)
    assert result is inner


def test_debug_transport_on_wraps(monkeypatch: pytest.MonkeyPatch) -> None:
    """DEBUG_HTTP=1 → debug_transport() returns a DebugTransport wrapper."""
    monkeypatch.setenv("DEBUG_HTTP", "1")

    import importlib
    import ark_agentic.core.llm.debug_transport as mod
    importlib.reload(mod)

    inner = MagicMock(spec=httpx.AsyncBaseTransport)
    result = mod.debug_transport(inner)
    assert isinstance(result, mod.DebugTransport)
    assert result._inner is inner  # noqa: SLF001


# ---------------------------------------------------------------------------
# Tests: DebugTransport request/response logging
# ---------------------------------------------------------------------------

@pytest.fixture
def _enable_http_debug_propagate():
    """Temporarily enable propagation so caplog can capture the debug logger."""
    dbg_logger = logging.getLogger("ark_agentic.http_debug")
    old = dbg_logger.propagate
    dbg_logger.propagate = True
    yield
    dbg_logger.propagate = old


@pytest.mark.asyncio
@pytest.mark.usefixtures("_enable_http_debug_propagate")
async def test_debug_transport_logs_request_and_response(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """DebugTransport logs request method/url/headers/body and response status/headers."""
    from ark_agentic.core.llm.debug_transport import DebugTransport

    chunks = [b'data: {"id":"1"}\n\n', b"data: [DONE]\n\n"]
    transport = DebugTransport(_OKTransport(chunks))
    request = _make_request()

    with caplog.at_level(logging.DEBUG, logger="ark_agentic.http_debug"):
        response = await transport.handle_async_request(request)

        collected: list[bytes] = []
        async for chunk in response.stream:
            collected.append(chunk)

    assert response.status_code == 200
    assert collected == chunks

    log_text = caplog.text
    assert ">>>" in log_text
    assert "POST" in log_text
    assert "gw.example.com" in log_text
    assert '{"model":"test"}' in log_text
    assert "<<<" in log_text
    assert "200" in log_text


@pytest.mark.asyncio
@pytest.mark.usefixtures("_enable_http_debug_propagate")
async def test_debug_transport_logs_streaming_chunks(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """_LoggingStream prints each non-empty line and a summary at the end."""
    from ark_agentic.core.llm.debug_transport import DebugTransport

    chunks = [
        b'data: {"delta":"A"}\n\n',
        b'data: {"delta":"B"}\n\n',
        b"data: [DONE]\n\n",
    ]
    transport = DebugTransport(_OKTransport(chunks))
    request = _make_request()

    with caplog.at_level(logging.DEBUG, logger="ark_agentic.http_debug"):
        response = await transport.handle_async_request(request)
        async for _ in response.stream:
            pass

    log_text = caplog.text
    assert "chunk |" in log_text
    assert "[DONE]" in log_text
    assert "stream done" in log_text
    assert "3 chunks" in log_text


@pytest.mark.asyncio
@pytest.mark.usefixtures("_enable_http_debug_propagate")
async def test_debug_transport_logs_connection_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """DebugTransport logs and re-raises connection errors."""
    from ark_agentic.core.llm.debug_transport import DebugTransport

    transport = DebugTransport(_ErrorTransport())
    request = _make_request()

    with caplog.at_level(logging.DEBUG, logger="ark_agentic.http_debug"):
        with pytest.raises(ConnectionError, match="connect timeout"):
            await transport.handle_async_request(request)

    assert "!!!" in caplog.text
    assert "connect timeout" in caplog.text


@pytest.mark.asyncio
async def test_logging_stream_aclose_delegates() -> None:
    """_LoggingStream.aclose() delegates to the inner stream."""
    from ark_agentic.core.llm.debug_transport import _LoggingStream

    inner = AsyncMock(spec=httpx.AsyncByteStream)
    inner.__aiter__ = AsyncMock(return_value=iter([]))
    stream = _LoggingStream(inner, "https://example.com")
    await stream.aclose()
    inner.aclose.assert_awaited_once()


# ---------------------------------------------------------------------------
# Tests: _LoggingStream is a proper AsyncByteStream
# ---------------------------------------------------------------------------

def test_logging_stream_inherits_async_byte_stream() -> None:
    from ark_agentic.core.llm.debug_transport import _LoggingStream
    assert issubclass(_LoggingStream, httpx.AsyncByteStream)


# ---------------------------------------------------------------------------
# Tests: make_debug_client()
# ---------------------------------------------------------------------------

def test_make_debug_client_returns_async_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """make_debug_client() returns an httpx.AsyncClient regardless of DEBUG_HTTP."""
    monkeypatch.delenv("DEBUG_HTTP", raising=False)

    import importlib
    import ark_agentic.core.llm.debug_transport as mod
    importlib.reload(mod)

    client = mod.make_debug_client()
    assert isinstance(client, httpx.AsyncClient)


def test_make_debug_client_wraps_when_debug_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """DEBUG_HTTP=1 → make_debug_client() uses DebugTransport internally."""
    monkeypatch.setenv("DEBUG_HTTP", "1")

    import importlib
    import ark_agentic.core.llm.debug_transport as mod
    importlib.reload(mod)

    client = mod.make_debug_client()
    assert isinstance(client, httpx.AsyncClient)
    transport = client._transport  # noqa: SLF001
    assert isinstance(transport, mod.DebugTransport)


@pytest.mark.asyncio
async def test_rewrite_url_async_transport_rewrites_chat_completions_url() -> None:
    """RewriteURLAsyncTransport replaces chat/completions with the configured full URL."""
    from ark_agentic.core.llm.debug_transport import RewriteURLAsyncTransport

    class _CaptureTransport(httpx.AsyncBaseTransport):
        def __init__(self) -> None:
            self.seen_url: httpx.URL | None = None

        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            self.seen_url = request.url
            return httpx.Response(status_code=200, stream=_FakeStream([]))

    inner = _CaptureTransport()
    transport = RewriteURLAsyncTransport(inner, "https://service-host/chat/dialog")
    await transport.handle_async_request(_make_request())

    assert str(inner.seen_url) == "https://service-host/chat/dialog"


def test_rewrite_url_transport_rewrites_sync_chat_completions_url() -> None:
    """RewriteURLTransport replaces chat/completions with the configured full URL."""
    from ark_agentic.core.llm.debug_transport import RewriteURLTransport

    class _CaptureTransport(httpx.BaseTransport):
        def __init__(self) -> None:
            self.seen_url: httpx.URL | None = None

        def handle_request(self, request: httpx.Request) -> httpx.Response:
            self.seen_url = request.url
            return httpx.Response(status_code=200, stream=_FakeSyncStream([]))

    inner = _CaptureTransport()
    transport = RewriteURLTransport(inner, "https://service-host/chat/dialog")
    transport.handle_request(_make_sync_request())

    assert str(inner.seen_url) == "https://service-host/chat/dialog"


def test_derive_base_url_for_full_url_uses_origin() -> None:
    from ark_agentic.core.llm.debug_transport import derive_base_url_for_full_url

    assert derive_base_url_for_full_url("https://service-host/chat/dialog") == "https://service-host/"


def test_derive_base_url_for_full_url_requires_absolute_url() -> None:
    from ark_agentic.core.llm.debug_transport import derive_base_url_for_full_url

    with pytest.raises(ValueError, match="absolute URL"):
        derive_base_url_for_full_url("/chat/dialog")
