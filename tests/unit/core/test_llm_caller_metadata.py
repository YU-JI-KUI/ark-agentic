"""Unit tests for LLMCaller typed-field writes (finish_reason, usage).

model_used and latency_ms were removed — they belong in monitoring dashboards,
not per-session timelines. finish_reason and usage are now typed fields on AgentMessage.
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
async def test_call_does_not_write_model_used_or_latency() -> None:
    """model_used and latency_ms are deleted — not written to metadata."""
    llm = _make_llm(model="my-model")
    llm.ainvoke = AsyncMock(return_value=AIMessage(content="hi"))
    caller = LLMCaller(llm)
    msg = await caller.call([], [])
    assert "model_used" not in msg.metadata
    assert "latency_ms" not in msg.metadata


@pytest.mark.asyncio
async def test_call_writes_finish_reason_as_typed_field() -> None:
    """finish_reason is a typed field, not stored in metadata."""
    ai_msg = AIMessage(content="hi")
    ai_msg.response_metadata = {"finish_reason": "stop"}
    llm = _make_llm()
    llm.ainvoke = AsyncMock(return_value=ai_msg)
    caller = LLMCaller(llm)
    msg = await caller.call([], [])
    assert msg.finish_reason == "stop"
    assert "finish_reason" not in msg.metadata


@pytest.mark.asyncio
async def test_call_does_not_write_sampling() -> None:
    llm = _make_llm(temperature=0.7, top_p=0.9)
    llm.ainvoke = AsyncMock(return_value=AIMessage(content="hi"))
    caller = LLMCaller(llm)
    msg = await caller.call([], [])
    assert "sampling" not in msg.metadata


@pytest.mark.asyncio
async def test_call_streaming_does_not_write_model_used_or_latency() -> None:
    """model_used and latency_ms are deleted from streaming path too."""
    llm = _make_llm(model="stream-model", temperature=0.3, top_p=1.0)

    async def _stream(*_a, **_k) -> AsyncIterator[AIMessageChunk]:
        yield AIMessageChunk(content="he")
        yield AIMessageChunk(content="llo")

    llm.astream = _stream
    caller = LLMCaller(llm)
    msg = await caller.call_streaming([], [])
    assert "model_used" not in msg.metadata
    assert "latency_ms" not in msg.metadata
    assert "sampling" not in msg.metadata


@pytest.mark.asyncio
async def test_call_streaming_writes_finish_reason_as_typed_field() -> None:
    """finish_reason from streaming path lands on the typed field."""
    llm = _make_llm()

    async def _stream(*_a, **_k) -> AsyncIterator[AIMessageChunk]:
        chunk = AIMessageChunk(content="hi")
        chunk.response_metadata = {"finish_reason": "stop"}
        yield chunk

    llm.astream = _stream
    caller = LLMCaller(llm)
    msg = await caller.call_streaming([], [])
    assert msg.finish_reason is not None
    assert "finish_reason" not in msg.metadata
