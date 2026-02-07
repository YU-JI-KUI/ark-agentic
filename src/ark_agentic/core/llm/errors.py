"""
结构化错误分类与模型 Fallback

参考: openclaw-main/src/agents/failover-error.ts, model-fallback.ts
"""

from __future__ import annotations

import logging
from enum import Enum
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


class LLMErrorReason(str, Enum):
    """LLM 错误原因分类"""

    AUTH = "auth"
    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    CONTEXT_OVERFLOW = "context_overflow"
    CONTENT_FILTER = "content_filter"
    SERVER_ERROR = "server_error"
    NETWORK = "network"
    UNKNOWN = "unknown"


@dataclass
class LLMError(Exception):
    """结构化 LLM 错误"""

    reason: LLMErrorReason
    message: str
    provider: str = ""
    model: str = ""
    status_code: int | None = None
    retryable: bool = False
    original: Exception | None = None

    def __str__(self) -> str:
        parts = [f"[{self.reason.value}]"]
        if self.provider:
            parts.append(f"provider={self.provider}")
        if self.model:
            parts.append(f"model={self.model}")
        if self.status_code:
            parts.append(f"status={self.status_code}")
        parts.append(self.message)
        return " ".join(parts)


def classify_error(
    exc: Exception,
    provider: str = "",
    model: str = "",
) -> LLMError:
    """将原始异常分类为结构化 LLMError。

    检测 HTTP 状态码和错误消息来判断错误类型。
    """
    import httpx

    status_code: int | None = None
    msg = str(exc)
    reason = LLMErrorReason.UNKNOWN
    retryable = False

    if isinstance(exc, httpx.HTTPStatusError):
        status_code = exc.response.status_code
        msg = exc.response.text[:500]

        if status_code == 401 or status_code == 403:
            reason = LLMErrorReason.AUTH
        elif status_code == 429:
            reason = LLMErrorReason.RATE_LIMIT
            retryable = True
        elif status_code == 413 or "context" in msg.lower() or "token" in msg.lower():
            reason = LLMErrorReason.CONTEXT_OVERFLOW
        elif status_code >= 500:
            reason = LLMErrorReason.SERVER_ERROR
            retryable = True
        elif status_code == 400 and ("content" in msg.lower() or "filter" in msg.lower()):
            reason = LLMErrorReason.CONTENT_FILTER

    elif isinstance(exc, (httpx.TimeoutException, TimeoutError)):
        reason = LLMErrorReason.TIMEOUT
        retryable = True

    elif isinstance(exc, (httpx.ConnectError, httpx.NetworkError, ConnectionError, OSError)):
        reason = LLMErrorReason.NETWORK
        retryable = True

    elif isinstance(exc, LLMError):
        return exc

    return LLMError(
        reason=reason,
        message=msg,
        provider=provider,
        model=model,
        status_code=status_code,
        retryable=retryable,
        original=exc,
    )


@dataclass
class FallbackModelConfig:
    """Fallback 模型配置"""

    provider: str
    model: str
    # 创建客户端所需的参数
    client_kwargs: dict[str, Any] = field(default_factory=dict)


@dataclass
class FallbackAttempt:
    """单次 fallback 尝试记录"""

    provider: str
    model: str
    error: LLMError | None = None
    success: bool = False


class FallbackLLMClient:
    """支持 Fallback 的 LLM 客户端包装器。

    按优先级尝试多个 LLM 客户端，遇到可重试错误时自动切换到下一个。

    参考: openclaw-main/src/agents/model-fallback.ts
    """

    def __init__(
        self,
        clients: list[tuple[str, str, Any]],
        max_retries_per_client: int = 1,
    ) -> None:
        """
        Args:
            clients: [(provider, model, client_instance), ...] 按优先级排序
            max_retries_per_client: 每个客户端最多重试次数
        """
        if not clients:
            raise ValueError("At least one client is required")
        self._clients = clients
        self._max_retries = max_retries_per_client
        self._attempts: list[FallbackAttempt] = []

    @property
    def attempts(self) -> list[FallbackAttempt]:
        return list(self._attempts)

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        stream: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """带 fallback 的聊天调用（仅非流式，流式不支持 fallback）"""
        self._attempts = []
        last_error: LLMError | None = None

        for provider, model, client in self._clients:
            attempt = FallbackAttempt(provider=provider, model=model)

            for retry in range(self._max_retries + 1):
                try:
                    result = await client.chat(
                        messages=messages,
                        tools=tools,
                        stream=False,  # fallback 只支持非流式
                        **kwargs,
                    )
                    attempt.success = True
                    self._attempts.append(attempt)

                    if len(self._attempts) > 1:
                        logger.info(
                            f"Fallback succeeded: {provider}/{model} "
                            f"(after {len(self._attempts) - 1} failures)"
                        )

                    return result

                except Exception as exc:
                    error = classify_error(exc, provider=provider, model=model)
                    attempt.error = error
                    last_error = error

                    logger.warning(
                        f"LLM call failed: {error} (retry {retry}/{self._max_retries})"
                    )

                    # 不可重试的错误（auth/context_overflow/content_filter）直接跳到下一个 client
                    if not error.retryable:
                        break

            self._attempts.append(attempt)

        # 所有客户端都失败了
        raise last_error or LLMError(
            reason=LLMErrorReason.UNKNOWN,
            message="All fallback models exhausted",
        )

    async def chat_streaming(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> Any:
        """流式调用（使用第一个客户端，不做 fallback）"""
        provider, model, client = self._clients[0]
        try:
            return await client.chat(
                messages=messages,
                tools=tools,
                stream=True,
                **kwargs,
            )
        except Exception as exc:
            raise classify_error(exc, provider=provider, model=model) from exc
