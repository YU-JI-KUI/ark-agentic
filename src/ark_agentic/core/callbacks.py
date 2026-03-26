"""Runner 生命周期回调

BeforeAgentCallback: 在 ReAct 循环前执行（准入检查 / 上下文预处理）
AfterAgentCallback:  在 ReAct 循环后执行（审计 / 指标采集）
RunnerCallbacks:     封装所有回调列表，保持 AgentRunner.__init__ 简洁
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from .stream.event_bus import AgentEventHandler
    from .types import AgentMessage, SessionEntry


@dataclass
class CallbackContext:
    """回调共享上下文 — 传递给所有 before/after 回调。

    Attributes:
        user_input: 原始用户输入
        input_context: 可变的请求级上下文 dict（before_agent 可修改）
        session: 当前 SessionEntry（只读引用，before_agent 阶段消息历史尚未包含本次 user_input）
        handler: 可选的事件处理器
    """
    user_input: str
    input_context: dict[str, Any]
    session: "SessionEntry"
    handler: "AgentEventHandler | None" = None


class BeforeAgentCallback(Protocol):
    """before_agent 回调协议。

    返回 None 表示继续执行；返回 (AgentMessage, dict) 表示短路退出。
    短路时 AgentMessage 作为助手回复，dict 为可选的 custom event data。
    """
    async def __call__(self, ctx: CallbackContext) -> tuple["AgentMessage", dict[str, Any]] | None: ...


class AfterAgentCallback(Protocol):
    async def __call__(self, ctx: CallbackContext, response: "AgentMessage") -> None: ...


@dataclass
class RunnerCallbacks:
    """封装所有回调列表，注入到 AgentRunner。"""
    before_agent: list[BeforeAgentCallback] = field(default_factory=list)
    after_agent: list[AfterAgentCallback] = field(default_factory=list)
