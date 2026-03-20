"""
流式事件总线

职责（SRP）：将 Runner 内部回调翻译为 AG-UI 原生 AgentStreamEvent 并推入队列。
扩展性（OCP）：新事件类型通过扩展 AgentEventHandler Protocol 添加。

状态管理：
  - 自动配对 step_started / step_finished
  - 自动配对 text_message_start / text_message_end
  - 终结事件（run_finished / run_error）自动关闭所有活跃状态
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Protocol

from .events import AgentStreamEvent

logger = logging.getLogger(__name__)


# ============ 回调协议（OCP 扩展点）============


class AgentEventHandler(Protocol):
    """Agent 事件回调协议。

    runner.py 依赖此协议而非具体实现（DIP）。
    添加新事件类型只需扩展此 Protocol，不修改 runner 核心逻辑。
    """

    def on_step(self, text: str) -> None:
        """Agent 生命周期步骤（如: "正在调用工具...", "正在思考..."）。"""
        ...

    def on_content_delta(self, delta: str, turn: int = 1) -> None:
        """最终回答的文本增量（逐 token 流式输出）。turn 为 ReAct 轮次（1-based）。"""
        ...

    def on_tool_call_start(self, tool_call_id: str, name: str, args: dict[str, Any]) -> None:
        """工具调用开始。"""
        ...

    def on_tool_call_result(self, tool_call_id: str, name: str, result: Any) -> None:
        """工具调用完成。"""
        ...

    def on_thinking_delta(self, delta: str, turn: int = 1) -> None:
        """思考过程文本增量（<think> 标签内容）。turn 为 ReAct 轮次（1-based）。"""
        ...

    def on_ui_component(self, component: dict[str, Any]) -> None:
        """A2UI 组件描述。"""
        ...


# ============ StreamEventBus 实现 ============


class StreamEventBus:
    """实现 AgentEventHandler，将回调转为 AG-UI 原生 AgentStreamEvent 推入 asyncio.Queue。

    内部维护 step / text_message 的活跃状态，自动配对 start/finish 事件。

    用法::

        queue = asyncio.Queue()
        bus = StreamEventBus(run_id="...", session_id="...", queue=queue)

        # 传给 runner
        await runner.run(..., handler=bus)

        # app.py 消费 queue
        while event := await queue.get():
            yield formatter.format(event)
    """

    def __init__(
        self,
        run_id: str,
        session_id: str,
        queue: asyncio.Queue[AgentStreamEvent],
    ) -> None:
        self._run_id = run_id
        self._session_id = session_id
        self._queue = queue
        self._seq = 0

        # 状态跟踪
        self._active_step: str | None = None
        self._text_started: bool = False
        self._text_message_id: str | None = None
        self._thinking_started: bool = False
        self._thinking_message_id: str | None = None

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def _emit(self, **kwargs: Any) -> None:
        """构建事件并推入队列。"""
        event = AgentStreamEvent(
            seq=self._next_seq(),
            run_id=self._run_id,
            session_id=self._session_id,
            **kwargs,
        )
        self._queue.put_nowait(event)

    def _close_active_step(self) -> None:
        """关闭当前活跃步骤（发送 step_finished）。"""
        if self._active_step is not None:
            self._emit(type="step_finished", step_name=self._active_step)
            self._active_step = None

    def _close_text_message(self) -> None:
        """关闭当前活跃文本消息（发送 text_message_end）。"""
        if self._text_started:
            self._emit(type="text_message_end", message_id=self._text_message_id)
            self._text_started = False
            self._text_message_id = None

    def _close_thinking_message(self) -> None:
        """关闭当前活跃思考消息（发送 thinking_message_end）。"""
        if self._thinking_started:
            self._emit(type="thinking_message_end", message_id=self._thinking_message_id)
            self._thinking_started = False
            self._thinking_message_id = None

    def _ensure_text_started(self) -> None:
        """确保文本消息已开始。"""
        if not self._text_started:
            self._text_message_id = str(uuid.uuid4())
            self._emit(type="text_message_start", message_id=self._text_message_id)
            self._text_started = True

    # ---- AgentEventHandler 实现 ----

    def on_step(self, text: str) -> None:
        if not text:
            return
        self._close_active_step()
        self._active_step = text
        self._emit(type="step_started", step_name=text)

    def on_thinking_delta(self, delta: str, turn: int = 1) -> None:
        if not delta:
            return
        if not self._thinking_started:
            self._thinking_message_id = str(uuid.uuid4())
            self._emit(type="thinking_message_start", message_id=self._thinking_message_id)
            self._thinking_started = True
        self._emit(
            type="thinking_message_content",
            delta=delta,
            message_id=self._thinking_message_id,
            turn=turn,
        )

    def on_content_delta(self, delta: str, turn: int = 1) -> None:
        if not delta:
            return
        self._ensure_text_started()
        self._emit(type="text_message_content", delta=delta, message_id=self._text_message_id, turn=turn)

    def on_tool_call_start(self, tool_call_id: str, name: str, args: dict[str, Any]) -> None:
        self._emit(
            type="tool_call_start",
            tool_call_id=tool_call_id,
            tool_name=name,
        )
        self._emit(
            type="tool_call_args",
            tool_call_id=tool_call_id,
            tool_name=name,
            tool_args=args,
        )

    def on_tool_call_result(self, tool_call_id: str, name: str, result: Any) -> None:
        result_str = str(result)
        if len(result_str) > 2000:
            result_str = result_str[:2000] + "... (truncated)"
        self._emit(
            type="tool_call_end",
            tool_call_id=tool_call_id,
            tool_name=name,
        )
        self._emit(
            type="tool_call_result",
            tool_call_id=tool_call_id,
            tool_name=name,
            tool_result=result_str,
        )

    def on_ui_component(self, component: dict[str, Any]) -> None:
        self._emit(
            type="text_message_content",
            content_kind="a2ui",
            custom_data=component,
        )

    # ---- 生命周期事件（由 app.py 直接调用）----

    def emit_created(self, content: str = "收到您的消息，正在处理中…") -> None:
        """发送 run_started 事件。"""
        self._emit(type="run_started", run_content=content)

    def emit_completed(
        self,
        message: str,
        *,
        tool_calls: list[dict[str, Any]] | None = None,
        turns: int = 0,
        usage: dict[str, int] | None = None,
    ) -> None:
        """发送 run_finished 事件。自动关闭活跃的 step、text_message 和 thinking_message。"""
        self._close_thinking_message()
        self._close_text_message()
        self._close_active_step()
        self._emit(
            type="run_finished",
            message=message,
            tool_calls=tool_calls,
            turns=turns,
            usage=usage,
        )

    def emit_failed(self, error_message: str) -> None:
        """发送 run_error 事件。自动关闭活跃的 step、text_message 和 thinking_message。"""
        self._close_thinking_message()
        self._close_text_message()
        self._close_active_step()
        self._emit(type="run_error", error_message=error_message)
