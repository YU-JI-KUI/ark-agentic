"""
Core LLM Error Handling

Minimal error classification and handling without complex fallback systems.
"""

from __future__ import annotations

import logging
from enum import Enum
from dataclasses import dataclass
from typing import Optional

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

    message: str
    reason: LLMErrorReason = LLMErrorReason.UNKNOWN
    provider: str = ""
    model: Optional[str] = None
    status_code: Optional[int] = None
    retryable: bool = False
    original_error: Optional[Exception] = None

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


def classify_error(error: Exception, model: Optional[str] = None) -> LLMError:
    """智能错误分类"""
    error_str = str(error).lower()

    # Authentication errors
    if any(keyword in error_str for keyword in [
        "unauthorized", "invalid api key", "authentication", "401"
    ]):
        return LLMError(
            f"Authentication error: {error}",
            reason=LLMErrorReason.AUTH,
            original_error=error,
            model=model
        )

    # Rate limit errors
    if any(keyword in error_str for keyword in [
        "rate limit", "too many requests", "429"
    ]):
        return LLMError(
            f"Rate limit error: {error}",
            reason=LLMErrorReason.RATE_LIMIT,
            original_error=error,
            model=model,
            retryable=True
        )

    # Timeout errors
    if any(keyword in error_str for keyword in [
        "timeout", "timed out", "connection timeout"
    ]):
        return LLMError(
            f"Timeout error: {error}",
            reason=LLMErrorReason.TIMEOUT,
            original_error=error,
            model=model,
            retryable=True
        )

    # Context overflow errors
    if any(keyword in error_str for keyword in [
        "context length", "token limit", "maximum context", "context overflow"
    ]):
        return LLMError(
            f"Context overflow error: {error}",
            reason=LLMErrorReason.CONTEXT_OVERFLOW,
            original_error=error,
            model=model
        )

    # Content filter errors
    if any(keyword in error_str for keyword in [
        "content filter", "content policy", "safety filter"
    ]):
        return LLMError(
            f"Content filter error: {error}",
            reason=LLMErrorReason.CONTENT_FILTER,
            original_error=error,
            model=model
        )

    # Server errors
    if any(keyword in error_str for keyword in [
        "500", "502", "503", "504", "server error", "internal error"
    ]):
        return LLMError(
            f"Server error: {error}",
            reason=LLMErrorReason.SERVER_ERROR,
            original_error=error,
            model=model,
            retryable=True
        )

    # Network errors
    if any(keyword in error_str for keyword in [
        "connection", "network", "dns", "host", "unreachable"
    ]):
        return LLMError(
            f"Network error: {error}",
            reason=LLMErrorReason.NETWORK,
            original_error=error,
            model=model,
            retryable=True
        )

    # Default to unknown
    return LLMError(
        f"Unknown LLM error: {error}",
        reason=LLMErrorReason.UNKNOWN,
        original_error=error,
        model=model
    )
