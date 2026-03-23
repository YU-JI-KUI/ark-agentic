"""
Agent 准入检查（Intake Guard）

提供通用的前置拦截协议：在进入 ReAct 循环之前判断请求是否在 Agent 受理范围内。
具体实现由各 Agent 提供（DIP）。
"""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel


class GuardResult(BaseModel):
    """准入检查结果。"""

    accepted: bool
    message: str | None = None


class IntakeGuard(Protocol):
    """准入检查协议。Runner 依赖此协议，具体实现由各 Agent 注入。"""

    async def check(self, user_input: str, context: dict[str, Any] | None = None) -> GuardResult: ...
