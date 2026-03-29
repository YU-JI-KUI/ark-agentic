"""Unit tests for LLMCaller."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage

from ark_agentic.core.llm.caller import LLMCaller


@pytest.mark.asyncio
async def test_call_maps_aimessage_to_agent_message() -> None:
    llm = MagicMock()
    llm.bind_tools = MagicMock(side_effect=lambda *a, **k: llm)
    llm.model_copy = MagicMock(side_effect=lambda update=None: llm)
    llm.ainvoke = AsyncMock(
        return_value=AIMessage(
            content="hello",
            tool_calls=[
                {
                    "id": "c1",
                    "name": "foo",
                    "args": {"x": 1},
                }
            ],
        )
    )
    caller = LLMCaller(llm)
    msg = await caller.call([{"role": "user", "content": "u"}], [])
    assert msg.role.value == "assistant"
    assert msg.content == "hello"
    assert msg.tool_calls and msg.tool_calls[0].name == "foo"


@pytest.mark.asyncio
async def test_call_wraps_generic_exception_as_llm_error() -> None:
    llm = MagicMock()
    llm.bind_tools = MagicMock(side_effect=lambda *a, **k: llm)
    llm.model_copy = MagicMock(side_effect=lambda update=None: llm)
    llm.ainvoke = AsyncMock(side_effect=ConnectionError("boom"))
    caller = LLMCaller(llm)
    from ark_agentic.core.llm.errors import LLMError

    with pytest.raises(LLMError):
        await caller.call([], [])
