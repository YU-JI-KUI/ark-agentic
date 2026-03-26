"""LLMCaller — 封装 LLM 调用（流式 / 非流式）

从 AgentRunner 中提取，职责单一：消息列表 + 工具 schema → AgentMessage。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage

from .errors import LLMError, classify_error
from ..stream.event_bus import AgentEventHandler
from ..types import AgentMessage, ToolCall

logger = logging.getLogger(__name__)


class LLMCaller:
    """LLM 调用封装（SRP: 只负责 LLM 交互与消息转换）"""

    def __init__(
        self,
        llm: BaseChatModel,
        *,
        enable_thinking_tags: bool = False,
    ) -> None:
        self._llm = llm
        self._enable_thinking_tags = enable_thinking_tags

    def get_llm(
        self,
        model_override: str | None = None,
        temperature_override: float | None = None,
    ) -> BaseChatModel:
        updates: dict[str, Any] = {}
        if model_override:
            updates["model"] = model_override
        if temperature_override is not None:
            updates["temperature"] = temperature_override
        if updates:
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
        temperature_override: float | None = None,
    ) -> AgentMessage:
        """非流式 LLM 调用"""
        llm = self.get_llm(model_override, temperature_override)
        if tools:
            llm = llm.bind_tools(tools)

        try:
            ai_msg = await llm.ainvoke(messages)
        except LLMError:
            raise
        except Exception as exc:
            raise classify_error(exc, model=model_override) from exc

        return self._ai_message_to_agent_message(ai_msg)

    async def call_streaming(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        model_override: str | None = None,
        temperature_override: float | None = None,
        content_callback: Callable[[str], None] | None = None,
        thinking_callback: Callable[[str], None] | None = None,
        handler: AgentEventHandler | None = None,
    ) -> AgentMessage:
        """流式 LLM 调用

        enable_thinking_tags 为 True 时，通过 ThinkingTagParser 解析
        <think>/<final> 标签路由到对应 callback。
        """
        from ..stream.thinking_tag_parser import ThinkingTagParser

        llm = self.get_llm(model_override, temperature_override)
        if tools:
            llm = llm.bind_tools(tools)

        model = model_override
        logger.info("LLM stream start | model=%s", model)

        parser = ThinkingTagParser() if self._enable_thinking_tags else None

        full_content = ""
        tool_calls_data: dict[int, dict[str, str]] = {}
        finish_reason = "stop"
        usage: dict[str, int] = {}

        try:
            async for chunk in llm.astream(messages):
                if chunk.content:
                    full_content += chunk.content  # type: ignore[operator]
                    if parser:
                        thinking, final = parser.process_chunk(chunk.content)  # type: ignore[arg-type]
                        if thinking and thinking_callback:
                            thinking_callback(thinking)
                        if final and content_callback:
                            content_callback(final)
                    elif content_callback:
                        content_callback(chunk.content)  # type: ignore[arg-type]

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

        except LLMError:
            raise
        except Exception as exc:
            raise classify_error(exc, model=model) from exc

        if parser:
            thinking, final = parser.flush()
            if thinking and thinking_callback:
                thinking_callback(thinking)
            if final and content_callback:
                content_callback(final)

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

        clean_content = ThinkingTagParser.strip_tags(full_content) if parser else full_content
        msg = AgentMessage.assistant(content=clean_content, tool_calls=parsed_tool_calls)
        msg.metadata["finish_reason"] = finish_reason
        if usage:
            msg.metadata["usage"] = usage

        if parser and not parser.ever_in_final and full_content:
            fallback = ThinkingTagParser.extract_non_think(full_content)
            if fallback:
                msg.metadata["thinking_fallback_content"] = fallback

        logger.debug("[LLM_STREAM_DONE] content=%dB tools=%d", len(full_content), len(tool_calls_data))
        return msg

    # ---- internal ----

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
