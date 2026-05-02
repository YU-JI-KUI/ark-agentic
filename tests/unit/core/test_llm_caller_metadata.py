"""Unit tests for LLMCaller metadata enrichment (model_used, latency_ms).

Sampling fields (temperature, top_p) are intentionally not stored — see
caller.py:_attach_call_metadata for rationale.
"""

from __future__ import annotations

from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk

from ark_agentic.core.llm.caller import LLMCaller


def _make_llm(
    *,
    model: str = "Qwen3-80B",
    temperature: float | None = 0.5,
    top_p: float | None = 0.8,
) -> MagicMock:
    llm = MagicMock()
    llm.model = model
    if temperature is not None:
        llm.temperature = temperature
    if top_p is not None:
        llm.top_p = top_p
    llm.bind_tools = MagicMock(side_effect=lambda *a, **k: llm)
    llm.model_copy = MagicMock(side_effect=lambda update=None: llm)
    return llm


@pytest.mark.asyncio
async def test_call_writes_model_used_and_latency() -> None:
    llm = _make_llm(model="my-model")
    llm.ainvoke = AsyncMock(return_value=AIMessage(content="hi"))
    caller = LLMCaller(llm)
    msg = await caller.call([], [])
    assert msg.metadata["model_used"] == "my-model"
    assert isinstance(msg.metadata["latency_ms"], int)
    assert msg.metadata["latency_ms"] >= 0


@pytest.mark.asyncio
async def test_call_does_not_write_sampling() -> None:
    llm = _make_llm(temperature=0.7, top_p=0.9)
    llm.ainvoke = AsyncMock(return_value=AIMessage(content="hi"))
    caller = LLMCaller(llm)
    msg = await caller.call([], [])
    assert "sampling" not in msg.metadata


@pytest.mark.asyncio
async def test_call_streaming_writes_metadata() -> None:
    llm = _make_llm(model="stream-model", temperature=0.3, top_p=1.0)

    async def _stream(*_a, **_k) -> AsyncIterator[AIMessageChunk]:
        yield AIMessageChunk(content="he")
        yield AIMessageChunk(content="llo")

    llm.astream = _stream
    caller = LLMCaller(llm)
    msg = await caller.call_streaming([], [])
    assert msg.metadata["model_used"] == "stream-model"
    assert "sampling" not in msg.metadata
    assert msg.metadata["latency_ms"] >= 0
    assert "finish_reason" in msg.metadata
