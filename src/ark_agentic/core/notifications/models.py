"""通知数据模型"""

from __future__ import annotations

import time
import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field


class Notification(BaseModel):
    notification_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    job_id: str                              # 来源 Job，如 "proactive_service"
    title: str
    body: str                                # 通知正文，支持 Markdown
    data: dict[str, Any] = Field(default_factory=dict)  # 结构化附加数据（如股价详情）
    created_at: float = Field(default_factory=time.time)
    read: bool = False
    priority: Literal["low", "normal", "high"] = "normal"


class NotificationList(BaseModel):
    notifications: list[Notification]
    total: int
    unread_count: int
