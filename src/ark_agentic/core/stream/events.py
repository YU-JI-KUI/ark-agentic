"""
统一流式事件模型

对齐 OpenAI Responses API 事件命名规范，扩展 tool_call 和 A2UI 支持。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


# ============ 事件类型常量 ============

EventType = Literal[
    "response.created",
    "response.step",
    "response.content.delta",
    "response.tool_call.start",
    "response.tool_call.result",
    "response.ui.component",
    "response.completed",
    "response.failed",
]


# ============ 统一事件模型 ============


class AgentStreamEvent(BaseModel):
    """统一流式事件。

    所有 Agent 的实时输出都封装为此模型，由 StreamEventBus 生成，
    通过 SSE / WebSocket / AG-UI 等传输层发送给前端。

    字段按事件类型选择性填充，其余为 None。
    """

    type: EventType = Field(..., description="事件类型")
    seq: int = Field(..., description="序号（单次 run 内递增）")
    run_id: str = Field(..., description="本次执行 ID")
    session_id: str = Field(..., description="会话 ID")

    # response.step — Agent 生命周期描述
    content: str | None = Field(None, description="步骤描述文本")

    # response.content.delta — 最终回答文本增量
    delta: str | None = Field(None, description="文本 delta")
    output_index: int | None = Field(None, description="输出块索引")

    # response.tool_call.* — 工具调用
    tool_name: str | None = Field(None, description="工具名称")
    tool_args: dict[str, Any] | None = Field(None, description="工具参数")
    tool_result: Any | None = Field(None, description="工具执行结果")

    # response.ui.component — A2UI 组件描述（预留）
    ui_component: dict[str, Any] | None = Field(None, description="A2UI 组件 JSON")

    # response.completed — 完成元数据
    message: str | None = Field(None, description="完整回答文本")
    usage: dict[str, int] | None = Field(None, description="Token 用量")
    turns: int | None = Field(None, description="ReAct 循环次数")
    tool_calls: list[dict[str, Any]] | None = Field(None, description="所有工具调用")

    # response.failed
    error_message: str | None = Field(None, description="错误信息")
