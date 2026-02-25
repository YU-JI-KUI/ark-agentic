"""
企业 AGUI 信封模型

对齐 A2UI-design.md §3.6 数据结构定义。
EnterpriseAGUIFormatter 使用这些模型将 AG-UI 原生事件包装为企业信封格式。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class AGUIDataPayload(BaseModel):
    """AGUI data 层字段（§3.6 data 参数定义）。"""

    code: str = "success"
    msg: str | None = None
    request_id: str | None = None
    trace_id: str | None = None
    message_id: str | None = None
    conversation_id: str | None = None
    timestamp: str = Field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"))

    ui_protocol: Literal["text", "json", "A2UI"] = "text"
    ui_data: Any = None
    turn: int | None = None  # ReAct 轮次（1-based），text_message_content 时设

    by: str | None = None
    to: str | None = None
    cost: str | None = None
    server: str | None = None
    extra: dict[str, Any] | None = None


class AGUIEnvelope(BaseModel):
    """企业级 AGUI 信封（§3.1 顶层结构）。

    protocol=AGUI 时，SSE 消息以此结构发送。
    """

    protocol: Literal["AGUI"] = "AGUI"
    id: int | str = 1
    event: str
    source_bu_type: str = ""
    app_type: str = ""
    data: AGUIDataPayload = Field(default_factory=AGUIDataPayload)
