"""
流式事件总线

职责（SRP）：将 Runner 内部回调翻译为 AgentStreamEvent 并推入队列。
扩展性（OCP）：新事件类型通过扩展 AgentEventHandler Protocol 添加。
"""

from __future__ import annotations

import asyncio
import logging
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

    def on_content_delta(self, delta: str, output_index: int = 0) -> None:
        """最终回答的文本增量（逐 token 流式输出）。"""
        ...

    def on_tool_call_start(self, name: str, args: dict[str, Any]) -> None:
        """工具调用开始。"""
        ...

    def on_tool_call_result(self, name: str, result: Any) -> None:
        """工具调用完成。"""
        ...

    def on_ui_component(self, component: dict[str, Any]) -> None:
        """A2UI 组件描述（预留扩展）。"""
        ...


# ============ StreamEventBus 实现 ============


class StreamEventBus:
    """实现 AgentEventHandler，将回调转为 AgentStreamEvent 推入 asyncio.Queue。

    用法::

        queue = asyncio.Queue()
        bus = StreamEventBus(run_id="...", session_id="...", queue=queue)

        # 传给 runner
        await runner.run(..., handler=bus)

        # app.py 消费 queue
        while event := await queue.get():
            yield f"event: {event.type}\\ndata: {event.model_dump_json()}\\n\\n"
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

    # ---- AgentEventHandler 实现 ----

    def on_step(self, text: str) -> None:
        if not text:
            return
        self._emit(type="response.step", content=text)

    def on_content_delta(self, delta: str, output_index: int = 0) -> None:
        if not delta:
            return
        self._emit(
            type="response.content.delta",
            delta=delta,
            output_index=output_index,
        )

    def on_tool_call_start(self, name: str, args: dict[str, Any]) -> None:
        self._emit(
            type="response.tool_call.start",
            tool_name=name,
            tool_args=args,
        )

    def on_tool_call_result(self, name: str, result: Any) -> None:
        # 截断过长的 tool result 避免 SSE 消息过大
        result_str = str(result)
        if len(result_str) > 2000:
            result_str = result_str[:2000] + "... (truncated)"
        self._emit(
            type="response.tool_call.result",
            tool_name=name,
            tool_result=result_str,
        )

    def on_ui_component(self, component: dict[str, Any]) -> None:
        self._emit(type="response.ui.component", ui_component=component)

    # ---- 生命周期事件（由 app.py 直接调用）----

    def emit_created(self, content: str = "收到您的消息，正在处理中…") -> None:
        """发送 response.created 事件。"""
        self._emit(type="response.created", content=content)

    def emit_completed(
        self,
        message: str,
        *,
        tool_calls: list[dict[str, Any]] | None = None,
        turns: int = 0,
        usage: dict[str, int] | None = None,
    ) -> None:
        """发送 response.completed 事件。"""
        self._emit(
            type="response.completed",
            message=message,
            tool_calls=tool_calls,
            turns=turns,
            usage=usage,
        )

    def emit_failed(self, error_message: str) -> None:
        """发送 response.failed 事件。"""
        self._emit(type="response.failed", error_message=error_message)
