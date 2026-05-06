"""LLM 调用重试（指数退避 + 抖动）。

对齐 Qwen-Agent base.py 的 retry_model_service 策略：
- 仅对 retryable=True 的错误重试（网络 / rate_limit / timeout / server_error）
- AUTH / QUOTA / CONTEXT_OVERFLOW / CONTENT_FILTER 直接抛出，不重试
- 指数退避：delay = min(base_delay * 2**attempt, max_delay) * jitter(0.5~1.0)
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any, AsyncIterator, Awaitable, Callable, TypeVar

from .errors import LLMError, LLMErrorReason, classify_error

logger = logging.getLogger(__name__)

T = TypeVar("T")

_NON_RETRYABLE: frozenset[LLMErrorReason] = frozenset(
    {
        LLMErrorReason.AUTH,
        LLMErrorReason.QUOTA,
        LLMErrorReason.CONTEXT_OVERFLOW,
        LLMErrorReason.CONTENT_FILTER,
    }
)


def _compute_delay(attempt: int, base_delay: float, max_delay: float) -> float:
    """指数退避 + 抖动。attempt 从 0 开始。"""
    delay = min(base_delay * (2**attempt), max_delay)
    jitter = 0.5 + random.random() * 0.5
    return delay * jitter


def _to_llm_error(exc: Exception, model: str | None) -> LLMError:
    if isinstance(exc, LLMError):
        return exc
    return classify_error(exc, model=model)


async def with_retry(
    fn: Callable[[], Awaitable[T]],
    *,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    model: str | None = None,
) -> T:
    """对异步函数进行指数退避重试。

    Args:
        fn: 无参异步函数（用 lambda / closure 绑定参数）
        max_retries: 最大重试次数（0 等同禁用，只调用一次）
        base_delay: 基础延迟（秒）
        max_delay: 最大延迟（秒）
        model: 模型名（用于错误分类日志）

    Returns:
        fn 的返回值

    Raises:
        LLMError: 非 retryable 错误立即抛出；retryable 错误达到上限时抛出最后一次
    """
    last_error: LLMError | None = None
    total_attempts = max_retries + 1

    for attempt in range(total_attempts):
        try:
            return await fn()
        except Exception as exc:
            llm_error = _to_llm_error(exc, model)

            if llm_error.reason in _NON_RETRYABLE or not llm_error.retryable:
                raise llm_error from exc

            last_error = llm_error
            if attempt >= max_retries:
                break

            delay = _compute_delay(attempt, base_delay, max_delay)
            logger.warning(
                "[LLM_RETRY] attempt=%d/%d reason=%s delay=%.2fs model=%s",
                attempt + 1,
                total_attempts,
                llm_error.reason.value,
                delay,
                model,
            )
            await asyncio.sleep(delay)

    assert last_error is not None
    raise last_error


async def with_retry_iterator(
    stream_fn: Callable[[], AsyncIterator[Any]],
    *,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    model: str | None = None,
) -> AsyncIterator[Any]:
    """对异步生成器进行指数退避重试。

    只在"开流前"发生的错误重试；一旦首个 chunk 产出即视为成功。
    这与 Qwen-Agent 的 _chat_stream 重试策略一致：避免中途重试造成重复输出。

    Args:
        stream_fn: 无参函数，返回 AsyncIterator
        max_retries / base_delay / max_delay / model: 同 with_retry

    Yields:
        stream_fn 产出的 chunk
    """
    last_error: LLMError | None = None
    total_attempts = max_retries + 1

    for attempt in range(total_attempts):
        try:
            iterator = stream_fn()
            first_chunk_yielded = False
            try:
                async for chunk in iterator:
                    first_chunk_yielded = True
                    yield chunk
                return
            except Exception as exc:
                if first_chunk_yielded:
                    raise _to_llm_error(exc, model) from exc
                llm_error = _to_llm_error(exc, model)
                if llm_error.reason in _NON_RETRYABLE or not llm_error.retryable:
                    raise llm_error from exc
                last_error = llm_error
        except LLMError:
            raise
        except Exception as exc:
            llm_error = _to_llm_error(exc, model)
            if llm_error.reason in _NON_RETRYABLE or not llm_error.retryable:
                raise llm_error from exc
            last_error = llm_error

        if attempt >= max_retries:
            break

        delay = _compute_delay(attempt, base_delay, max_delay)
        logger.warning(
            "[LLM_STREAM_RETRY] attempt=%d/%d reason=%s delay=%.2fs model=%s",
            attempt + 1,
            total_attempts,
            last_error.reason.value if last_error else "unknown",
            delay,
            model,
        )
        await asyncio.sleep(delay)

    assert last_error is not None
    raise last_error
