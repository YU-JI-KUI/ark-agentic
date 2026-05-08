"""
TextLeakGuard — 工具调用推理文字防泄露拦截器

职责：在 SSE 推送层拦截 AG-UI 事件流，缓冲每一轮的 text 事件，
等确认本轮无工具调用后，再以延迟回放方式推给前端（伪 streaming）。

设计原则：
- 对 runner / formatter / event_bus 完全无感知，只感知 AgentStreamEvent.type
- 无外部依赖，可独立单元测试
- 延迟通过 STREAM_CHUNK_DELAY_MS 环境变量配置（默认 20ms）
"""

from __future__ import annotations

import asyncio
import os
from typing import AsyncIterator, Callable

from .events import AgentStreamEvent

# 每个原始 chunk 回放时的间隔（秒），可通过环境变量调整
_CHUNK_DELAY: float = float(os.getenv("STREAM_CHUNK_DELAY_MS", "20")) / 1000.0

# text 类事件：需要缓冲、等待本轮结束后决策的事件
_TEXT_EVENT_TYPES = frozenset(
    {"text_message_start", "text_message_content", "text_message_end"}
)

FormatFn = Callable[[AgentStreamEvent], str | None]


class TextLeakGuard:
    """SSE 推送层的文字防泄露拦截器。

    每次 HTTP 请求（run）创建一个实例，跨事件维护缓冲状态：

    - text_message_* 事件先缓冲，不立即发给前端
    - 检测到 tool_call_start → 本轮有工具调用，丢弃缓冲的 text
    - 检测到 run_finished   → 本轮无工具调用，flush 缓冲（带 sleep 延迟伪 streaming）

    工具类事件（tool_call_*）和其他事件（step_*、thinking_*、custom 等）直接透传。
    """

    def __init__(self) -> None:
        self._text_buffer: list[AgentStreamEvent] = []
        self._has_tool_call: bool = False

    async def process(
        self,
        event: AgentStreamEvent,
        fmt: FormatFn,
    ) -> AsyncIterator[str]:
        """处理单个 AG-UI 事件，yield 零个或多个格式化后的 SSE 行。

        Args:
            event: 来自 StreamEventBus 的原始事件
            fmt:   OutputFormatter.format 方法（或任意 FormatFn 实现）
        """
        if event.type in _TEXT_EVENT_TYPES:
            # A2UI 卡片组件通过 on_ui_component 发出，类型也是 text_message_content，
            # 但 content_kind="a2ui"。卡片是工具执行结果的渲染，必须直接透传，不参与缓冲。
            if event.content_kind == "a2ui":
                line = fmt(event)
                if line:
                    yield line
                return

            # text_message_start 标志着新一轮文字输出的开始：
            # 重置 has_tool_call 标记，使本轮可以独立判断是否有工具调用。
            # 这样多轮场景下（工具调用轮 → 最终回答轮），最终回答轮的文字不会
            # 被上一轮的工具调用状态错误地丢弃。
            if event.type == "text_message_start":
                self._has_tool_call = False
                self._text_buffer.clear()
            self._text_buffer.append(event)
            return

        if event.type == "tool_call_start":
            # 本轮确认有工具调用：丢弃已缓冲的推理文字，直接透传工具事件
            self._text_buffer.clear()
            self._has_tool_call = True
            line = fmt(event)
            if line:
                yield line
            return

        if event.type == "run_finished":
            # 本轮结束：
            # - 无工具调用 → flush 缓冲（伪 streaming 回放，每 chunk 间加短暂延迟）
            # - 有工具调用 → 缓冲早已被清空，无需处理
            if not self._has_tool_call:
                for buffered in self._text_buffer:
                    line = fmt(buffered)
                    if line:
                        yield line
                    await asyncio.sleep(_CHUNK_DELAY)
            # 重置状态（一般一个 run 只有一个 run_finished，保险起见仍重置）
            self._text_buffer.clear()
            self._has_tool_call = False
            line = fmt(event)
            if line:
                yield line
            return

        # 其余事件（tool_call_args/end/result, step_*, thinking_*, custom 等）直接透传
        line = fmt(event)
        if line:
            yield line