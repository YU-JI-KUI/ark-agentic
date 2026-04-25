"""Unit tests for LLM retry utilities."""

from __future__ import annotations

from typing import AsyncIterator

import pytest

from ark_agentic.core.llm.errors import LLMError, LLMErrorReason
from ark_agentic.core.llm.retry import with_retry, with_retry_iterator


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Replace asyncio.sleep with a capturing no-op for deterministic tests."""
    recorded: list[float] = []

    async def _fake_sleep(delay: float) -> None:
        recorded.append(delay)

    monkeypatch.setattr("ark_agentic.core.llm.retry.asyncio.sleep", _fake_sleep)
    return recorded


class TestWithRetry:
    @pytest.mark.asyncio
    async def test_returns_value_on_first_success(
        self, _no_real_sleep: list[float]
    ) -> None:
        calls = 0

        async def _fn() -> str:
            nonlocal calls
            calls += 1
            return "ok"

        result = await with_retry(_fn, max_retries=3)
        assert result == "ok"
        assert calls == 1
        assert _no_real_sleep == []

    @pytest.mark.asyncio
    async def test_retries_on_retryable_and_eventually_succeeds(
        self, _no_real_sleep: list[float]
    ) -> None:
        calls = 0

        async def _fn() -> str:
            nonlocal calls
            calls += 1
            if calls < 3:
                raise TimeoutError("timed out")
            return "ok"

        result = await with_retry(_fn, max_retries=3, base_delay=1.0, max_delay=10.0)
        assert result == "ok"
        assert calls == 3
        assert len(_no_real_sleep) == 2

    @pytest.mark.asyncio
    async def test_exponential_backoff_bounded_by_max_delay(
        self, _no_real_sleep: list[float]
    ) -> None:
        async def _fn() -> str:
            raise TimeoutError("timed out")

        with pytest.raises(LLMError) as exc_info:
            await with_retry(_fn, max_retries=4, base_delay=1.0, max_delay=4.0)

        assert exc_info.value.reason == LLMErrorReason.TIMEOUT
        assert len(_no_real_sleep) == 4
        # Delay = min(base*2**attempt, max_delay) * jitter(0.5~1.0)
        # attempt=0 → ≤1; attempt=1 → ≤2; attempt=2 → ≤4; attempt=3 → ≤4
        assert _no_real_sleep[0] <= 1.0
        assert _no_real_sleep[1] <= 2.0
        assert _no_real_sleep[2] <= 4.0
        assert _no_real_sleep[3] <= 4.0
        for d in _no_real_sleep:
            assert d > 0

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "err_keyword, expected_reason",
        [
            ("invalid api key", LLMErrorReason.AUTH),
            ("maximum context exceeded", LLMErrorReason.CONTEXT_OVERFLOW),
            ("content filter triggered", LLMErrorReason.CONTENT_FILTER),
            ("insufficient balance", LLMErrorReason.QUOTA),
        ],
    )
    async def test_non_retryable_errors_raised_without_retry(
        self,
        _no_real_sleep: list[float],
        err_keyword: str,
        expected_reason: LLMErrorReason,
    ) -> None:
        calls = 0

        async def _fn() -> str:
            nonlocal calls
            calls += 1
            raise RuntimeError(err_keyword)

        with pytest.raises(LLMError) as exc_info:
            await with_retry(_fn, max_retries=5)

        assert exc_info.value.reason == expected_reason
        assert calls == 1
        assert _no_real_sleep == []

    @pytest.mark.asyncio
    async def test_max_retries_zero_calls_once(
        self, _no_real_sleep: list[float]
    ) -> None:
        calls = 0

        async def _fn() -> str:
            nonlocal calls
            calls += 1
            raise TimeoutError("timed out")

        with pytest.raises(LLMError):
            await with_retry(_fn, max_retries=0)

        assert calls == 1
        assert _no_real_sleep == []

    @pytest.mark.asyncio
    async def test_final_attempt_error_is_raised(
        self, _no_real_sleep: list[float]
    ) -> None:
        calls = 0

        async def _fn() -> str:
            nonlocal calls
            calls += 1
            raise ConnectionError(f"network-{calls}")

        with pytest.raises(LLMError) as exc_info:
            await with_retry(_fn, max_retries=2)

        assert exc_info.value.reason == LLMErrorReason.NETWORK
        assert "network-3" in str(exc_info.value)
        assert calls == 3
        assert len(_no_real_sleep) == 2

    @pytest.mark.asyncio
    async def test_passes_through_existing_llm_error_classification(
        self, _no_real_sleep: list[float]
    ) -> None:
        async def _fn() -> str:
            raise LLMError(
                "custom", reason=LLMErrorReason.AUTH, retryable=False
            )

        with pytest.raises(LLMError) as exc_info:
            await with_retry(_fn, max_retries=3)

        assert exc_info.value.reason == LLMErrorReason.AUTH
        assert _no_real_sleep == []


class TestWithRetryIterator:
    @staticmethod
    def _make_stream_fn(
        script: list[list[str] | Exception],
    ):
        idx = [0]

        def _factory() -> AsyncIterator[str]:
            current = idx[0]
            idx[0] += 1

            async def _iter() -> AsyncIterator[str]:
                item = script[current]
                if isinstance(item, Exception):
                    raise item
                for chunk in item:
                    yield chunk

            return _iter()

        return _factory, idx

    @pytest.mark.asyncio
    async def test_yields_chunks_from_successful_stream(
        self, _no_real_sleep: list[float]
    ) -> None:
        async def _iter() -> AsyncIterator[str]:
            for c in ["a", "b", "c"]:
                yield c

        chunks: list[str] = []
        async for c in with_retry_iterator(_iter, max_retries=2):
            chunks.append(c)

        assert chunks == ["a", "b", "c"]
        assert _no_real_sleep == []

    @pytest.mark.asyncio
    async def test_retries_on_startup_failure_then_succeeds(
        self, _no_real_sleep: list[float]
    ) -> None:
        factory, idx = self._make_stream_fn(
            [ConnectionError("network oops"), ["hello", "world"]]
        )

        chunks: list[str] = []
        async for c in with_retry_iterator(factory, max_retries=3):
            chunks.append(c)

        assert chunks == ["hello", "world"]
        assert idx[0] == 2
        assert len(_no_real_sleep) == 1

    @pytest.mark.asyncio
    async def test_non_retryable_error_raised_immediately(
        self, _no_real_sleep: list[float]
    ) -> None:
        factory, idx = self._make_stream_fn([RuntimeError("invalid api key")])

        with pytest.raises(LLMError) as exc_info:
            async for _ in with_retry_iterator(factory, max_retries=3):
                pass

        assert exc_info.value.reason == LLMErrorReason.AUTH
        assert idx[0] == 1
        assert _no_real_sleep == []

    @pytest.mark.asyncio
    async def test_mid_stream_failure_is_not_retried(
        self, _no_real_sleep: list[float]
    ) -> None:
        """Once the first chunk is yielded, mid-stream errors are raised as-is."""

        async def _iter() -> AsyncIterator[str]:
            yield "first"
            raise TimeoutError("mid-stream timeout")

        chunks: list[str] = []
        with pytest.raises(LLMError) as exc_info:
            async for c in with_retry_iterator(_iter, max_retries=3):
                chunks.append(c)

        assert chunks == ["first"]
        assert exc_info.value.reason == LLMErrorReason.TIMEOUT
        assert _no_real_sleep == []

    @pytest.mark.asyncio
    async def test_max_retries_zero_does_not_retry(
        self, _no_real_sleep: list[float]
    ) -> None:
        factory, idx = self._make_stream_fn(
            [TimeoutError("boom"), ["never-reached"]]
        )

        with pytest.raises(LLMError):
            async for _ in with_retry_iterator(factory, max_retries=0):
                pass

        assert idx[0] == 1
        assert _no_real_sleep == []
