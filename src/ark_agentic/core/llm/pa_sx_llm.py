"""
PA-SX LLM：Trace Header 由 Transport 注入，Body 由 ChatOpenAI(extra_body) 在构造时注入。
Bearer 由 ChatOpenAI(api_key=...) 注入。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import httpx

from .sampling import SamplingConfig

if TYPE_CHECKING:
    from langchain_core.language_models.chat_models import BaseChatModel
    from .factory import PAModelConfig

logger = logging.getLogger(__name__)


# ============ SX Transport ============


class PASXTraceTransport(httpx.AsyncBaseTransport):
    """httpx 异步 Transport：为 PA-SX 请求仅注入 trace Header（不修改 body）。"""

    def __init__(
        self,
        *,
        base_transport: httpx.AsyncBaseTransport | None = None,
        trace_app_id: str = "",
        trace_source: str = "",
        trace_user_id: str = "",
    ) -> None:
        self._transport = base_transport or httpx.AsyncHTTPTransport(retries=3)
        self._trace_app_id = trace_app_id
        self._trace_source = trace_source
        self._trace_user_id = trace_user_id

    def _build_trace_headers(self) -> dict[str, str]:
        return {
            "trace-appId": self._trace_app_id,
            "trace-source": self._trace_source,
            "trace-userId": self._trace_user_id,
        }

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        request.headers.update(self._build_trace_headers())
        return await self._transport.handle_async_request(request)


# ============ Builder ============


def create_pa_sx_llm(
    config: "PAModelConfig",
    *,
    sampling: SamplingConfig,
    streaming: bool = False,
) -> "BaseChatModel":
    """构建 PA-SX 系列 ChatOpenAI。

    Body 通过 extra_body 在构造时注入，从源头保证 Content-Length 正确。
    采样参数统一由 SamplingConfig 分层注入。
    """
    from langchain_openai import ChatOpenAI
    from .debug_transport import debug_transport

    transport = PASXTraceTransport(
        base_transport=debug_transport(httpx.AsyncHTTPTransport(retries=3)),
        trace_app_id=config.trace_app_id,
    )
    http_client = httpx.AsyncClient(transport=transport)
    logger.info(f"PA-SX model {config.model_name} with trace transport")

    return ChatOpenAI(
        base_url=config.base_url,
        api_key=config.api_key or "EMPTY",
        model=config.model_name,
        streaming=streaming,
        http_async_client=http_client,
        extra_body=sampling.to_extra_body(),
        **sampling.to_chat_openai_kwargs(),
    )
