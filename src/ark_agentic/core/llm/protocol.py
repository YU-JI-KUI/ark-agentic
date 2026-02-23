"""
LangChain LLM Protocol

Protocol abstraction over ChatOpenAI for dependency inversion.
"""

from __future__ import annotations

from typing import Any, AsyncIterator, Protocol, runtime_checkable, TYPE_CHECKING

if TYPE_CHECKING:
    from langchain_openai import ChatOpenAI
    from langchain_core.messages import AIMessage, AIMessageChunk
    from langchain_core.language_models.chat_models import BaseChatModel


@runtime_checkable
class LangChainLLMProtocol(Protocol):
    """Protocol for LLM clients following LangChain interface.

    Abstracts the key methods that AgentRunner needs from ChatOpenAI.
    """

    async def ainvoke(self, messages: list[dict[str, Any]]) -> AIMessage:
        """Non-streaming LLM invocation.

        Args:
            messages: List of messages in OpenAI format

        Returns:
            AIMessage instance with response
        """
        ...

    def astream(self, messages: list[dict[str, Any]]) -> AsyncIterator[AIMessageChunk]:
        """Streaming LLM invocation.

        Args:
            messages: List of messages in OpenAI format

        Returns:
            AsyncIterator of AIMessageChunk instances
        """
        ...

    def bind_tools(self, tools: list[dict[str, Any]]) -> LangChainLLMProtocol:
        """Bind tool definitions to the LLM.

        Args:
            tools: List of tool definitions in OpenAI format

        Returns:
            New LLM instance with tools bound
        """
        ...

    def model_copy(self, *, update: dict[str, Any]) -> LangChainLLMProtocol:
        """Create a copy with updated parameters.

        Args:
            update: Dictionary of parameters to update

        Returns:
            New LLM instance with updated parameters
        """
        ...

    def copy(self, *, update: dict[str, Any]) -> LangChainLLMProtocol:
        """Create a copy with updated parameters.

        Args:
            update: Dictionary of parameters to update

        Returns:
            New LLM instance with updated parameters
        """
        ...


class ChatOpenAIWrapper:
    """Wrapper that adapts ChatOpenAI to LangChainLLMProtocol."""

    def __init__(self, chat_openai: ChatOpenAI) -> None:
        """Initialize wrapper with ChatOpenAI instance.

        Args:
            chat_openai: ChatOpenAI instance from langchain-openai
        """
        self._llm = chat_openai

    async def ainvoke(self, messages: list[dict[str, Any]]) -> AIMessage:
        """Delegate to ChatOpenAI.ainvoke."""
        return await self._llm.ainvoke(messages)

    def astream(self, messages: list[dict[str, Any]]) -> AsyncIterator[AIMessageChunk]:
        """Delegate to ChatOpenAI.astream."""
        return self._llm.astream(messages)

    def bind_tools(self, tools: list[dict[str, Any]]) -> LangChainLLMProtocol:
        """Delegate to ChatOpenAI.bind_tools and wrap result."""
        bound_llm = self._llm.bind_tools(tools)
        return ChatOpenAIWrapper(bound_llm)

    def model_copy(self, *, update: dict[str, Any]) -> LangChainLLMProtocol:
        """Delegate to ChatOpenAI.model_copy and wrap result."""
        if hasattr(self._llm, "model_copy"):
            copied_llm = self._llm.model_copy(update=update)
            return ChatOpenAIWrapper(copied_llm)
        elif hasattr(self._llm, "copy"):
            # Fallback for older Pydantic versions
            copied_llm = self._llm.copy(update=update)
            return ChatOpenAIWrapper(copied_llm)
        else:
            # If no copy method available, return self
            return self

    def copy(self, *, update: dict[str, Any]) -> LangChainLLMProtocol:
        """Delegate to ChatOpenAI.copy and wrap result."""
        if hasattr(self._llm, "copy"):
            copied_llm = self._llm.copy(update=update)
            return ChatOpenAIWrapper(copied_llm)
        elif hasattr(self._llm, "model_copy"):
            # Fallback to model_copy for newer Pydantic versions
            copied_llm = self._llm.model_copy(update=update)
            return ChatOpenAIWrapper(copied_llm)
        else:
            # If no copy method available, return self
            return self

    def __getattr__(self, name: str) -> Any:
        """Delegate any other attribute access to the wrapped ChatOpenAI instance."""
        return getattr(self._llm, name)


def wrap_chat_openai(chat_openai: ChatOpenAI) -> LangChainLLMProtocol:
    """Convenience function to wrap ChatOpenAI instances.

    Args:
        chat_openai: ChatOpenAI instance from langchain-openai

    Returns:
        Wrapped instance conforming to LangChainLLMProtocol
    """
    return ChatOpenAIWrapper(chat_openai)