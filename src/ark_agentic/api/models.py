"""
API 请求/响应数据模型

从 app.py 中提取的 Pydantic BaseModel 定义。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from ark_agentic.core.types import RunOptions


# ── Chat ────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    """Chat 请求模型"""
    agent_id: str = Field("insurance", description="Agent ID (insurance/securities)")
    message: str = Field(..., description="用户消息内容")
    session_id: str | None = Field(None, description="会话 ID，为空则创建新会话")
    stream: bool = Field(False, description="是否启用 SSE 流式输出")
    run_options: RunOptions | None = Field(None, description="运行选项（模型、温度等覆盖）")
    # 流式协议选择
    protocol: str = Field("internal", description="流式输出协议 (agui/internal/enterprise/alone)")
    source_bu_type: str = Field("", description="BU 来源（enterprise 模式使用）")
    app_type: str = Field("", description="App 类型（enterprise 模式使用）")
    # 业务上下文字段
    user_id: str | None = Field(None, description="用户 ID")
    context: dict[str, Any] | None = Field(None, description="业务上下文数据")
    idempotency_key: str | None = Field(None, description="幂等键，防止重复请求")


class ChatResponse(BaseModel):
    """Chat 响应模型"""
    session_id: str
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


