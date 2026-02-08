"""
流式输出组装器

参考: openclaw-main/src/tui/tui-stream-assembler.ts

处理 LLM 流式响应，组装完整的消息内容。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Callable

from ..types import AgentMessage, ToolCall

logger = logging.getLogger(__name__)


class StreamEventType(str, Enum):
    """流式事件类型"""

    # 内容事件
    CONTENT_START = "content_start"
    CONTENT_DELTA = "content_delta"
    CONTENT_END = "content_end"

    # 思考事件（extended thinking）
    THINKING_START = "thinking_start"
    THINKING_DELTA = "thinking_delta"
    THINKING_END = "thinking_end"

    # 工具调用事件
    TOOL_USE_START = "tool_use_start"
    TOOL_USE_DELTA = "tool_use_delta"
    TOOL_USE_END = "tool_use_end"

    # 消息事件
    MESSAGE_START = "message_start"
    MESSAGE_END = "message_end"

    # 错误事件
    ERROR = "error"


@dataclass
class StreamEvent:
    """流式事件"""

    type: StreamEventType
    data: Any = None
    index: int = 0  # 用于多个内容块的索引


@dataclass
class StreamState:
    """流式状态"""

    # 内容累积
    content: str = ""
    thinking: str = ""

    # 工具调用累积
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    current_tool_index: int = -1
    current_tool_input: str = ""

    # 状态标志
    is_complete: bool = False
    error: str | None = None

    # 统计
    input_tokens: int = 0
    output_tokens: int = 0


class StreamAssembler:
    """流式输出组装器

    将 LLM 的流式响应组装成完整的 AgentMessage。

    支持:
    - 文本内容累积
    - 思考过程（thinking）累积
    - 工具调用参数累积和解析
    - 事件回调
    """

    def __init__(
        self,
        on_content: Callable[[str], None] | None = None,
        on_thinking: Callable[[str], None] | None = None,
        on_tool_call: Callable[[ToolCall], None] | None = None,
        on_complete: Callable[[AgentMessage], None] | None = None,
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        """
        Args:
            on_content: 内容增量回调
            on_thinking: 思考增量回调
            on_tool_call: 工具调用完成回调
            on_complete: 消息完成回调
            on_error: 错误回调
        """
        self._on_content = on_content
        self._on_thinking = on_thinking
        self._on_tool_call = on_tool_call
        self._on_complete = on_complete
        self._on_error = on_error

        self._state = StreamState()

    def reset(self) -> None:
        """重置状态"""
        self._state = StreamState()

    @property
    def state(self) -> StreamState:
        """当前状态"""
        return self._state

    def process_event(self, event: StreamEvent) -> None:
        """处理单个流式事件"""
        handlers = {
            StreamEventType.CONTENT_DELTA: self._handle_content_delta,
            StreamEventType.THINKING_DELTA: self._handle_thinking_delta,
            StreamEventType.TOOL_USE_START: self._handle_tool_start,
            StreamEventType.TOOL_USE_DELTA: self._handle_tool_delta,
            StreamEventType.TOOL_USE_END: self._handle_tool_end,
            StreamEventType.MESSAGE_END: self._handle_message_end,
            StreamEventType.ERROR: self._handle_error,
        }

        handler = handlers.get(event.type)
        if handler:
            handler(event)

    def _handle_content_delta(self, event: StreamEvent) -> None:
        """处理内容增量"""
        delta = event.data or ""
        self._state.content += delta
        if self._on_content:
            self._on_content(delta)

    def _handle_thinking_delta(self, event: StreamEvent) -> None:
        """处理思考增量"""
        delta = event.data or ""
        self._state.thinking += delta

        if self._on_thinking:
            self._on_thinking(delta)

    def _handle_tool_start(self, event: StreamEvent) -> None:
        """处理工具调用开始"""
        tool_data = event.data or {}
        self._state.current_tool_index = len(self._state.tool_calls)
        self._state.current_tool_input = ""
        self._state.tool_calls.append({
            "id": tool_data.get("id", ""),
            "name": tool_data.get("name", ""),
            "input": "",
        })

    def _handle_tool_delta(self, event: StreamEvent) -> None:
        """处理工具调用参数增量"""
        delta = event.data or ""
        self._state.current_tool_input += delta

        if self._state.current_tool_index >= 0:
            self._state.tool_calls[self._state.current_tool_index]["input"] = (
                self._state.current_tool_input
            )

    def _handle_tool_end(self, event: StreamEvent) -> None:
        """处理工具调用结束"""
        if self._state.current_tool_index >= 0:
            tool_data = self._state.tool_calls[self._state.current_tool_index]

            # 解析 JSON 参数
            try:
                arguments = json.loads(tool_data["input"]) if tool_data["input"] else {}
            except json.JSONDecodeError:
                arguments = {"_raw": tool_data["input"]}

            tool_call = ToolCall(
                id=tool_data["id"],
                name=tool_data["name"],
                arguments=arguments,
            )

            if self._on_tool_call:
                self._on_tool_call(tool_call)

        self._state.current_tool_index = -1
        self._state.current_tool_input = ""

    def _handle_message_end(self, event: StreamEvent) -> None:
        """处理消息结束"""
        self._state.is_complete = True

        # 解析 usage
        if event.data and isinstance(event.data, dict):
            usage = event.data.get("usage", {})
            self._state.input_tokens = usage.get("input_tokens", 0)
            self._state.output_tokens = usage.get("output_tokens", 0)

        # 构建最终消息
        message = self.build_message()

        if self._on_complete:
            self._on_complete(message)

    def _handle_error(self, event: StreamEvent) -> None:
        """处理错误"""
        self._state.error = str(event.data)

        if self._on_error:
            self._on_error(self._state.error)

    def build_message(self) -> AgentMessage:
        """构建最终的 AgentMessage"""
        # 解析工具调用
        tool_calls: list[ToolCall] | None = None
        if self._state.tool_calls:
            tool_calls = []
            for tc in self._state.tool_calls:
                try:
                    arguments = json.loads(tc["input"]) if tc["input"] else {}
                except json.JSONDecodeError:
                    arguments = {"_raw": tc["input"]}

                tool_calls.append(ToolCall(
                    id=tc["id"],
                    name=tc["name"],
                    arguments=arguments,
                ))

        return AgentMessage.assistant(
            content=self._state.content or None,
            tool_calls=tool_calls,
            thinking=self._state.thinking or None,
        )

    async def process_stream(
        self, stream: AsyncIterator[StreamEvent]
    ) -> AgentMessage:
        """处理完整的事件流

        Args:
            stream: 事件流迭代器

        Returns:
            组装完成的消息
        """
        self.reset()

        async for event in stream:
            self.process_event(event)

            if self._state.error:
                raise RuntimeError(f"Stream error: {self._state.error}")

        return self.build_message()


# ============ Anthropic/OpenAI 格式转换 ============


def parse_anthropic_sse(data: dict[str, Any]) -> StreamEvent | None:
    """解析 Anthropic SSE 格式

    参考: https://docs.anthropic.com/en/api/messages-streaming
    """
    event_type = data.get("type")

    if event_type == "message_start":
        return StreamEvent(type=StreamEventType.MESSAGE_START, data=data.get("message"))

    elif event_type == "content_block_start":
        block = data.get("content_block", {})
        block_type = block.get("type")
        index = data.get("index", 0)

        if block_type == "text":
            return StreamEvent(type=StreamEventType.CONTENT_START, index=index)
        elif block_type == "thinking":
            return StreamEvent(type=StreamEventType.THINKING_START, index=index)
        elif block_type == "tool_use":
            return StreamEvent(
                type=StreamEventType.TOOL_USE_START,
                index=index,
                data={"id": block.get("id"), "name": block.get("name")},
            )

    elif event_type == "content_block_delta":
        delta = data.get("delta", {})
        delta_type = delta.get("type")
        index = data.get("index", 0)

        if delta_type == "text_delta":
            return StreamEvent(
                type=StreamEventType.CONTENT_DELTA,
                index=index,
                data=delta.get("text", ""),
            )
        elif delta_type == "thinking_delta":
            return StreamEvent(
                type=StreamEventType.THINKING_DELTA,
                index=index,
                data=delta.get("thinking", ""),
            )
        elif delta_type == "input_json_delta":
            return StreamEvent(
                type=StreamEventType.TOOL_USE_DELTA,
                index=index,
                data=delta.get("partial_json", ""),
            )

    elif event_type == "content_block_stop":
        index = data.get("index", 0)
        # 需要根据上下文判断是哪种类型的结束
        return StreamEvent(type=StreamEventType.TOOL_USE_END, index=index)

    elif event_type == "message_delta":
        return None  # 通常只包含 stop_reason

    elif event_type == "message_stop":
        return StreamEvent(type=StreamEventType.MESSAGE_END, data=data)

    elif event_type == "error":
        return StreamEvent(type=StreamEventType.ERROR, data=data.get("error"))

    return None


def parse_openai_sse(data: dict[str, Any]) -> StreamEvent | None:
    """解析 OpenAI SSE 格式

    参考: https://platform.openai.com/docs/api-reference/chat/streaming
    """
    choices = data.get("choices", [])
    if not choices:
        return None

    choice = choices[0]
    delta = choice.get("delta", {})
    finish_reason = choice.get("finish_reason")

    # 内容增量
    if "content" in delta and delta["content"]:
        return StreamEvent(
            type=StreamEventType.CONTENT_DELTA,
            data=delta["content"],
        )

    # 工具调用
    if "tool_calls" in delta:
        tool_calls = delta["tool_calls"]
        if tool_calls:
            tc = tool_calls[0]
            index = tc.get("index", 0)

            if "function" in tc:
                func = tc["function"]
                if "name" in func:
                    # 工具开始
                    return StreamEvent(
                        type=StreamEventType.TOOL_USE_START,
                        index=index,
                        data={"id": tc.get("id", ""), "name": func["name"]},
                    )
                elif "arguments" in func:
                    # 参数增量
                    return StreamEvent(
                        type=StreamEventType.TOOL_USE_DELTA,
                        index=index,
                        data=func["arguments"],
                    )

    # 结束
    if finish_reason:
        return StreamEvent(
            type=StreamEventType.MESSAGE_END,
            data={"finish_reason": finish_reason, "usage": data.get("usage")},
        )

    return None
