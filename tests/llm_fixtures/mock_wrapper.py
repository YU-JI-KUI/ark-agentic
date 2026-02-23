"""
Mock LLM Protocol Wrapper (test fixture)

Adapts MockLLMClient to LangChainLLMProtocol for use with AgentRunner in tests.
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

from ark_agentic.core.llm.protocol import LangChainLLMProtocol

from .mock import MockLLMClient


class MockAIMessage:
    """Mock AIMessage that mimics LangChain's AIMessage interface."""

    def __init__(self, content: str = "", tool_calls: list[dict[str, Any]] | None = None):
        self.content = content
        self.tool_calls = tool_calls or []
        self.response_metadata = {"finish_reason": "stop"}
        self.usage_metadata = {
            "input_tokens": 10,
            "output_tokens": len(content.split()) if content else 0,
        }


class MockAIMessageChunk:
    """Mock AIMessageChunk for streaming (not implemented in MockLLMClient)."""

    def __init__(self, content: str = "", tool_call_chunks: list[dict[str, Any]] | None = None):
        self.content = content
        self.tool_call_chunks = tool_call_chunks or []
        self.response_metadata = {"finish_reason": "stop"}
        self.usage_metadata = {"input_tokens": 5, "output_tokens": 5}


class MockLLMWrapper:
    """Adapts MockLLMClient to LangChainLLMProtocol."""

    def __init__(self, mock_client: MockLLMClient | None = None):
        self._mock_client = mock_client or MockLLMClient()

    async def ainvoke(self, messages: list[dict[str, Any]]) -> MockAIMessage:
        """Convert LangChain ainvoke to MockLLMClient.chat()."""
        response = await self._mock_client.chat(messages, tools=None, stream=False)

        if isinstance(response, dict) and "choices" in response:
            choice = response["choices"][0]
            message = choice["message"]

            content = message.get("content", "")
            tool_calls = message.get("tool_calls", [])

            langchain_tool_calls = []
            if tool_calls:
                for tc in tool_calls:
                    langchain_tool_calls.append({
                        "id": tc["id"],
                        "name": tc["function"]["name"],
                        "args": json.loads(tc["function"]["arguments"]),
                    })

            ai_message = MockAIMessage(content=content, tool_calls=langchain_tool_calls)
            ai_message.response_metadata["finish_reason"] = choice.get("finish_reason", "stop")
            return ai_message

        return MockAIMessage(content="Mock response")

    async def astream(self, messages: list[dict[str, Any]]) -> AsyncIterator[MockAIMessageChunk]:
        """Mock streaming (MockLLMClient doesn't support real streaming)."""
        ai_message = await self.ainvoke(messages)
        chunk = MockAIMessageChunk(content=ai_message.content)
        chunk.response_metadata = ai_message.response_metadata
        chunk.usage_metadata = ai_message.usage_metadata
        yield chunk

    def bind_tools(self, tools: list[dict[str, Any]]) -> LangChainLLMProtocol:
        """Return self since MockLLMClient handles tools internally."""
        return self

    def model_copy(self, *, update: dict[str, Any]) -> LangChainLLMProtocol:
        """Return self since MockLLMClient doesn't need parameter updates."""
        return self

    def copy(self, *, update: dict[str, Any]) -> LangChainLLMProtocol:
        """Return self since MockLLMClient doesn't need parameter updates."""
        return self


def wrap_mock_llm(mock_client: MockLLMClient | None = None) -> LangChainLLMProtocol:
    """Wrap MockLLMClient as LangChainLLMProtocol.

    Args:
        mock_client: Optional MockLLMClient instance. If None, creates a new one.

    Returns:
        Wrapped MockLLMClient that implements LangChainLLMProtocol
    """
    return MockLLMWrapper(mock_client)
