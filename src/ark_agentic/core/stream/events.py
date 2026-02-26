"""
AG-UI 原生流式事件模型

对齐 AG-UI 协议标准事件类型（17种），作为内部事件总线的原生格式。
输出层（OutputFormatter）负责适配到不同的传输协议。

5个 Runner 回调信号 → StreamEventBus 展开为完整 AG-UI 事件序列：

  Runner signal              AG-UI events produced
  ─────────────────────────────────────────────────────────────
  on_step(text)           →  step_finished(prev?) + step_started
  on_content_delta(x)     →  text_message_start(if new) + text_message_content
  on_tool_call_start(...) →  tool_call_start + tool_call_args
  on_tool_call_result(...) → tool_call_end + tool_call_result
  on_ui_component(c)      →  text_message_content (content_kind=a2ui, custom_data=component)

  app.py 直接调用:
  emit_created()          →  run_started
  emit_completed()        →  text_message_end? + step_finished? + run_finished
  emit_failed()           →  text_message_end? + step_finished? + run_error
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


# ============ AG-UI 事件类型常量（完整17种）============

EventType = Literal[
    # 核心生命周期 (§3.3 #1-3)
    "run_started",
    "run_finished",
    "run_error",
    # 子步骤 (§3.3 #4-5)
    "step_started",
    "step_finished",
    # 文本流 (§3.3 #6-8)
    "text_message_start",
    "text_message_content",
    "text_message_end",
    # 工具调用 (§3.3 #9-12)
    "tool_call_start",
    "tool_call_args",
    "tool_call_end",
    "tool_call_result",
    # 状态同步 (§3.3 #13-14)
    "state_snapshot",
    "state_delta",
    # 消息快照 (§3.3 #15)
    "messages_snapshot",
    # 自定义 / 原始透传 (§3.3 #16-17)
    "custom",
    "raw",
]


# ============ 统一事件模型 ============


class AgentStreamEvent(BaseModel):
    """AG-UI 原生流式事件。

    所有 Agent 的实时输出都封装为此模型，由 StreamEventBus 生成，
    通过 OutputFormatter 适配到不同传输协议后发送给前端。

    字段按事件类型选择性填充，其余为 None。
    """

    type: EventType = Field(..., description="AG-UI 事件类型")
    seq: int = Field(..., description="序号（单次 run 内递增）")
    run_id: str = Field(..., description="本次执行 ID")
    session_id: str = Field(..., description="会话 ID")

    # run_started — 初始化消息
    run_content: str | None = Field(None, description="run_started 描述文本")

    # step_started / step_finished
    step_name: str | None = Field(None, description="步骤名称/描述")

    # text_message_start / text_message_content / text_message_end
    message_id: str | None = Field(None, description="文本消息 ID（跨事件关联键）")

    # text_message_content
    delta: str | None = Field(None, description="文本 delta")
    turn: int | None = Field(None, description="本条文本所属的 ReAct 轮次（1-based），用于区分中间轮与最终轮")
    content_kind: Literal["text", "a2ui"] | None = Field(
        None,
        description="text_message_content 时：text=普通文本，a2ui=A2UI 组件",
    )

    # tool_call_start / tool_call_args / tool_call_end / tool_call_result
    tool_call_id: str | None = Field(None, description="工具调用 ID（AG-UI 关联键）")
    tool_name: str | None = Field(None, description="工具名称")
    tool_args: dict[str, Any] | None = Field(None, description="工具参数")
    tool_result: Any | None = Field(None, description="工具执行结果")

    # custom — A2UI / 自定义组件
    custom_type: str | None = Field(None, description="自定义事件子类型")
    custom_data: dict[str, Any] | None = Field(None, description="自定义事件数据")

    # run_finished — 完成元数据
    message: str | None = Field(None, description="完整回答文本")
    usage: dict[str, int] | None = Field(None, description="Token 用量")
    turns: int | None = Field(None, description="ReAct 循环次数")
    tool_calls: list[dict[str, Any]] | None = Field(None, description="所有工具调用")

    # run_error
    error_message: str | None = Field(None, description="错误信息")
