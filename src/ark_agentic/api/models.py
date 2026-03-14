"""
API 请求/响应数据模型

从 app.py 中提取的 Pydantic BaseModel 定义。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from ark_agentic.core.types import RunOptions


# ── Chat ────────────────────────────────────────────────────────────


class HistoryMessage(BaseModel):
    """External chat history message (user/assistant only)."""

    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    """Chat 请求模型"""
    agent_id: str = Field("insurance", description="Agent ID (insurance/securities)")
    message: str = Field(..., description="用户消息内容")
    session_id: str | None = Field(None, description="会话 ID，为空则创建新会话")
    stream: bool = Field(False, description="是否启用 SSE 流式输出")
    run_options: RunOptions | None = Field(None, description="运行选项（模型、温度等覆盖）")
    protocol: str = Field("internal", description="流式输出协议 (agui/internal/enterprise/alone)")
    source_bu_type: str = Field("", description="BU 来源（enterprise 模式使用）")
    app_type: str = Field("", description="App 类型（enterprise 模式使用）")
    user_id: str | None = Field(None, description="用户 ID（body 或 header 至少提供一个）")
    message_id: str | None = Field(None, description="消息 ID，为空则自动生成 UUID")
    context: dict[str, Any] | None = Field(None, description="业务上下文数据")
    idempotency_key: str | None = Field(None, description="幂等键，防止重复请求")
    # 外部聊天历史
    history: list[HistoryMessage] | None = Field(None, description="外部系统聊天历史（最近 N 轮）")
    use_history: bool = Field(True, description="是否启用外部历史合并")


class ChatResponse(BaseModel):
    """Chat 响应模型"""
    session_id: str
    message_id: str
    response: str
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    turns: int = 0
    usage: dict[str, int] | None = Field(None, description="Token 使用统计")


# ── SSE ─────────────────────────────────────────────────────────────

class SSEEvent(BaseModel):
    """SSE event — aligned with OpenAI Responses API naming.

    Event types:
      - response.created       : Run initialized
      - response.step          : Agent lifecycle step (tool, status)
      - response.content.delta : Final answer text chunk (typewriter)
      - response.template      : JSON template card
      - response.completed     : Run finished with metadata
      - response.failed        : Error
    """
    type: str = Field(..., description="Event type (response.*)")
    seq: int = Field(..., description="Sequence number")
    run_id: str | None = Field(None)
    session_id: str | None = Field(None)
    # Step
    content: str | None = Field(None, description="Step description text")
    # Content delta
    delta: str | None = Field(None, description="Answer text chunk")
    output_index: int | None = Field(None, description="Output block index")
    # Template
    template: dict[str, Any] | None = Field(None, description="JSON template card data")
    # Completed
    message: str | None = Field(None, description="Full answer text")
    usage: dict[str, int] | None = Field(None)
    turns: int | None = Field(None)
    tool_calls: list[dict[str, Any]] | None = Field(None)
    # Failed
    error_message: str | None = Field(None)


