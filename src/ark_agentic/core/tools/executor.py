"""ToolExecutor — 工具执行 + ToolEvent 统一分发

从 AgentRunner._execute_tools 提取。职责：
1. 按序执行工具调用（含超时 / 错误兜底）
2. 将 AgentToolResult.events 统一分发到 AgentEventHandler
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from ..stream.event_bus import AgentEventHandler
from ..types import (
    AgentToolResult,
    CustomToolEvent,
    StepToolEvent,
    ToolCall,
    ToolLoopAction,
    ToolResultType,
    UIComponentToolEvent,
)
from .registry import ToolRegistry

logger = logging.getLogger(__name__)


class ToolExecutor:
    """工具执行器（SRP: 只负责执行工具 + 分发事件）"""

    def __init__(
        self,
        registry: ToolRegistry,
        *,
        timeout: float = 30.0,
        max_calls_per_turn: int = 5,
    ) -> None:
        self._registry = registry
        self._timeout = timeout
        self._max_calls_per_turn = max_calls_per_turn

    async def execute(
        self,
        tool_calls: list[ToolCall],
        context: dict[str, Any],
        handler: AgentEventHandler | None = None,
    ) -> list[AgentToolResult]:
        """全并行执行所有 tool_calls，完成后按原始顺序合并副作用。"""
        ctx = {**context, "_tool_results_by_name": dict(context.get("_tool_results_by_name") or {})}

        limited = tool_calls[: self._max_calls_per_turn]
        if len(tool_calls) > len(limited):
            logger.warning("[TOOLS_LIMIT] requested=%d limited=%d", len(tool_calls), len(limited))

        results = await asyncio.gather(
            *[self._execute_single(tc, {**ctx}, handler) for tc in limited]
        )

        for tc, result in zip(limited, results):
            self._dispatch_events(result, handler)

            state_delta = result.metadata.get("state_delta") if result.metadata else None
            if isinstance(state_delta, dict) and state_delta:
                ctx.update(state_delta)
            by_name = ctx.get("_tool_results_by_name") or {}
            by_name[tc.name] = result.content
            ctx["_tool_results_by_name"] = by_name

        return list(results)

    async def _execute_single(
        self,
        tc: ToolCall,
        ctx: dict[str, Any],
        handler: AgentEventHandler | None,
    ) -> AgentToolResult:
        logger.debug("[TOOL_START] %s args=%s", tc.name, tc.arguments)

        tool = self._registry.get(tc.name)
        if handler:
            handler.on_tool_call_start(tc.id, tc.name, tc.arguments)
            status = tool.thinking_hint if tool and tool.thinking_hint else f"正在处理 {tc.name}…"
            handler.on_step(status)

        if tool is None:
            result = AgentToolResult.error_result(tc.id, f"Tool not found: {tc.name}")
        else:
            try:
                result = await asyncio.wait_for(tool.execute(tc, ctx), timeout=self._timeout)
            except asyncio.TimeoutError:
                logger.error("Tool execution timeout: %s (%ss)", tc.name, self._timeout)
                result = AgentToolResult.error_result(tc.id, f"Tool '{tc.name}' timed out after {self._timeout}s")
            except Exception as e:
                logger.error("[TOOL_ERROR] %s: %s", tc.name, e)
                result = AgentToolResult.error_result(tc.id, str(e))

        if handler:
            handler.on_tool_call_result(tc.id, tc.name, result.content)

        logger.debug("[TOOL_DONE] %s error=%s size=%dB", tc.name, result.is_error, len(str(result.content)))
        if result.is_error and handler:
            handler.on_step("工具调用遇到问题，正在尝试其他方式…")

        return result

    _RESULT_TYPE_TO_PROTOCOL: dict[ToolResultType, str] = {
        ToolResultType.JSON: "json",
        ToolResultType.TEXT: "text",
        ToolResultType.A2UI: "A2UI",
        ToolResultType.IMAGE: "json",
        ToolResultType.ERROR: "text",
    }

    @staticmethod
    def _dispatch_events(
        result: AgentToolResult,
        handler: AgentEventHandler | None,
    ) -> None:
        """统一分发 ToolEvent 到 handler — 工具只声明事件，不依赖 handler (DIP)。"""
        if not handler or not result.events:
            return
        for evt in result.events:
            if isinstance(evt, UIComponentToolEvent):
                handler.on_ui_component(evt.component)
            elif isinstance(evt, CustomToolEvent):
                ui_protocol = ToolExecutor._RESULT_TYPE_TO_PROTOCOL.get(result.result_type, "json")
                payload = {**evt.payload, "ui_protocol": ui_protocol}
                handler.on_custom_event(evt.custom_type, payload)
            elif isinstance(evt, StepToolEvent):
                handler.on_step(evt.text)
