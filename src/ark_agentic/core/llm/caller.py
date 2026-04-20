"""LLMCaller — 封装 LLM 调用（流式 / 非流式）

职责：
- 消息列表 + 工具 schema → AgentMessage
- 流式/非流式均通过 with_retry / with_retry_iterator 执行指数退避重试
- 流式模式识别 Thinking 模型原生 reasoning_content 字段，路由到 thinking_callback
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage

from .errors import LLMError
from .retry import with_retry, with_retry_iterator
from .sampling import SamplingConfig
from ..types import AgentMessage, ToolCall

logger = logging.getLogger(__name__)


class LLMCaller:
    """LLM 调用封装（SRP: 只负责 LLM 交互与消息转换）。"""

    def __init__(
        self,
        llm: BaseChatModel,
        *,
        max_retries: int = 3,
    ) -> None:
        self._llm = llm
        self._max_retries = max_retries

    def get_llm(
        self,
        *,
        model_override: str | None = None,
        sampling_override: SamplingConfig | None = None,
    ) -> BaseChatModel:
        """按需返回 LLM 实例（支持模型 / 采样覆盖）。

        sampling_override 用于 background 调用（memory flush / dream / summarize），
        让其复用主 LLM 的连接层但使用专用采样参数。
        """
        updates: dict[str, Any] = {}
        if model_override:
            updates["model"] = model_override
        if sampling_override is not None:
            updates.update(sampling_override.to_chat_openai_kwargs())
            current_body = getattr(self._llm, "extra_body", None) or {}
            updates["extra_body"] = {
                **current_body,
                **sampling_override.to_extra_body(),
            }

        if not updates:
            return self._llm

        if hasattr(self._llm, "model_copy"):
            return self._llm.model_copy(update=updates)
        if hasattr(self._llm, "copy"):
            return self._llm.copy(update=updates)
        logger.debug("LLM backend lacks model_copy/copy; ignoring overrides: %s", updates)
        return self._llm

    async def call(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        model_override: str | None = None,
        sampling_override: SamplingConfig | None = None,
    ) -> AgentMessage:
        """非流式 LLM 调用（外层自动重试）。"""
        llm = self.get_llm(
            model_override=model_override,
            sampling_override=sampling_override,
        )
        if tools:
            llm = llm.bind_tools(tools)

        async def _invoke() -> AIMessage:
            return await llm.ainvoke(messages)

        ai_msg = await with_retry(
            _invoke,
            max_retries=self._max_retries,
            model=model_override,
        )
        return self._ai_message_to_agent_message(ai_msg)

    async def call_streaming(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        model_override: str | None = None,
        sampling_override: SamplingConfig | None = None,
        content_callback: Callable[[str], None] | None = None,
        thinking_callback: Callable[[str], None] | None = None,
    ) -> AgentMessage:
        """流式 LLM 调用（外层自动重试）。

        Thinking 模型（如 Qwen3-Thinking / DeepSeek-R1）会在 chunk.additional_kwargs
        里返回独立的 reasoning_content 字段；此处识别并路由到 thinking_callback，
        前端 UI 复用现有 on_thinking_delta 事件流，无需感知模型差异。
        """
        llm = self.get_llm(
            model_override=model_override,
            sampling_override=sampling_override,
        )
        if tools:
            llm = llm.bind_tools(tools)

        model = model_override
        logger.info("LLM stream start | model=%s", model)

        full_content = ""
        tool_calls_data: dict[int, dict[str, str]] = {}
        finish_reason = "stop"
        usage: dict[str, int] = {}

        def _stream_factory():
            return llm.astream(messages)

        async for chunk in with_retry_iterator(
            _stream_factory,
            max_retries=self._max_retries,
            model=model,
        ):
            reasoning = ""
            if hasattr(chunk, "additional_kwargs") and chunk.additional_kwargs:
                reasoning_raw = chunk.additional_kwargs.get("reasoning_content")
                if isinstance(reasoning_raw, str):
                    reasoning = reasoning_raw
            if reasoning and thinking_callback:
                thinking_callback(reasoning)

            if chunk.content:
                text = chunk.content if isinstance(chunk.content, str) else str(chunk.content)
                full_content += text
                if content_callback:
                    content_callback(text)

            if hasattr(chunk, "tool_call_chunks") and chunk.tool_call_chunks:  # type: ignore[attr-defined]
                for tc_chunk in chunk.tool_call_chunks:  # type: ignore[attr-defined]
                    raw = tc_chunk if isinstance(tc_chunk, dict) else dict(tc_chunk)
                    idx = int(raw.get("index") or 0)
                    if idx not in tool_calls_data:
                        tool_calls_data[idx] = {"id": "", "name": "", "args": ""}
                    if raw.get("id"):
                        tool_calls_data[idx]["id"] = str(raw["id"])
                    if raw.get("name"):
                        tool_calls_data[idx]["name"] = str(raw["name"])
                    args_delta = raw.get("args")
                    if args_delta is not None and args_delta != "":
                        tool_calls_data[idx]["args"] += (
                            args_delta if isinstance(args_delta, str) else str(args_delta)
                        )

            if hasattr(chunk, "response_metadata") and chunk.response_metadata:
                finish_reason = chunk.response_metadata.get("finish_reason", finish_reason)
            if hasattr(chunk, "usage_metadata") and chunk.usage_metadata:
                usage = {
                    "prompt_tokens": chunk.usage_metadata.get("input_tokens", 0),
                    "completion_tokens": chunk.usage_metadata.get("output_tokens", 0),
                }

        parsed_tool_calls = None
        if tool_calls_data:
            parsed_tool_calls = []
            for idx in sorted(tool_calls_data):
                tc = tool_calls_data[idx]
                try:
                    args = json.loads(tc["args"]) if tc["args"] else {}
                except json.JSONDecodeError:
                    args = {"_raw": tc["args"]}
                parsed_tool_calls.append(ToolCall(id=tc["id"], name=tc["name"], arguments=args))

        msg = AgentMessage.assistant(content=full_content, tool_calls=parsed_tool_calls)
        msg.metadata["finish_reason"] = finish_reason
        if usage:
            msg.metadata["usage"] = usage

        logger.debug(
            "[LLM_STREAM_DONE] content=%dB tools=%d", len(full_content), len(tool_calls_data)
        )
        return msg

    @staticmethod
    def _ai_message_to_agent_message(ai_msg: AIMessage) -> AgentMessage:
        content = ai_msg.content if isinstance(ai_msg.content, str) else ""

        tool_calls = None
        if ai_msg.tool_calls:
            tool_calls = [
                ToolCall(id=tc["id"], name=tc["name"], arguments=tc.get("args", {}))
                for tc in ai_msg.tool_calls
            ]

        msg = AgentMessage.assistant(content=content, tool_calls=tool_calls)

        rm = getattr(ai_msg, "response_metadata", {}) or {}
        msg.metadata["finish_reason"] = rm.get("finish_reason", "stop")

        um = getattr(ai_msg, "usage_metadata", None)
        if um:
            msg.metadata["usage"] = {
                "prompt_tokens": um.get("input_tokens", 0),
                "completion_tokens": um.get("output_tokens", 0),
            }

        return msg
