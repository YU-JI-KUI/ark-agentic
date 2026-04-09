"""Runner 生命周期回调

7 个 hook 覆盖 Agent 执行全生命周期:

  Agent 级 (run 方法, 各触发一次):
    before_agent → after_agent

  ReAct Loop 级 (每轮触发):
    before_model → after_model → before_tool → after_tool

  ReAct Loop 级 (仅在最终 response 轮触发，一次或多次):
    before_loop_end

所有 hook 返回 CallbackResult | None。
CallbackResult.action (HookAction enum) 声明回调的意图：
  PASS     — 不干预，走默认流程
  ABORT    — before_agent: 拒绝请求，退出 run
  OVERRIDE — before_model / before_tool: 替换默认输出
  RETRY    — before_loop_end: 注入反馈，让模型重试
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from .types import AgentMessage, AgentToolResult, SessionEntry, ToolCall


# ============ Result Types ============


class HookAction(str, Enum):
    """回调声明的动作意图 — 由 runner 按 hook 上下文执行。"""
    PASS = "pass"
    ABORT = "abort"
    OVERRIDE = "override"
    RETRY = "retry"


@dataclass
class CallbackEvent:
    """Typed event for the runner to dispatch via handler."""
    type: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class CallbackResult:
    """Declares changes a callback wants applied.

    Callbacks produce this; the runner consumes and applies.
    None-valued fields = no change for that aspect.
    """
    action: HookAction = HookAction.PASS
    response: "AgentMessage | None" = None
    tool_results: "list[AgentToolResult] | None" = None
    context_updates: dict[str, Any] | None = None
    event: CallbackEvent | None = None


# ============ Shared Context ============


@dataclass
class CallbackContext:
    """回调共享上下文 — 传递给所有 hook。

    Attributes:
        user_input: 原始用户输入
        input_context: 请求级上下文 dict（通过 CallbackResult.context_updates 修改）
        session: 当前 SessionEntry（只读引用）
    """
    user_input: str
    input_context: dict[str, Any]
    session: "SessionEntry"


# ============ Hook Protocols ============


class BeforeAgentCallback(Protocol):
    """before_agent: fires once before the ReAct loop.

    action=ABORT + response → reject request, return response as reply.
    context_updates → merge into input_context before loop entry.
    event → runner dispatches via handler.
    """
    async def __call__(self, ctx: CallbackContext) -> CallbackResult | None: ...


class AfterAgentCallback(Protocol):
    """after_agent: fires once after the ReAct loop completes."""
    async def __call__(self, ctx: CallbackContext, *, response: "AgentMessage") -> CallbackResult | None: ...


class BeforeModelCallback(Protocol):
    """before_model: fires before each LLM call.

    action=OVERRIDE + response → skip LLM call, use response as model output.
    Does NOT fire on LLMError turns.
    """
    async def __call__(self, ctx: CallbackContext, *, turn: int, messages: list[dict[str, Any]]) -> CallbackResult | None: ...


class AfterModelCallback(Protocol):
    """after_model: fires after successful LLM response, before persist.

    response override → replace the model's response before it is persisted.
    Does NOT fire on LLMError.
    """
    async def __call__(self, ctx: CallbackContext, *, turn: int, response: "AgentMessage") -> CallbackResult | None: ...


class BeforeToolCallback(Protocol):
    """before_tool: fires before tool execution batch (once per turn).

    action=OVERRIDE + tool_results → skip tool execution, use these results.
    """
    async def __call__(self, ctx: CallbackContext, *, turn: int, tool_calls: list["ToolCall"]) -> CallbackResult | None: ...


class AfterToolCallback(Protocol):
    """after_tool: fires after tool execution + state_delta merge.

    tool_results override → replace the tool results.
    """
    async def __call__(self, ctx: CallbackContext, *, turn: int, results: list["AgentToolResult"]) -> CallbackResult | None: ...


class BeforeLoopEndCallback(Protocol):
    """before_loop_end: fires when the model produces a final (non-tool-call) response,
    just before _finalize_response is called.

    action=RETRY + response=feedback_msg → inject feedback_msg into session as a user
    message and continue the ReAct loop, allowing the model to self-correct.
    action=PASS / None → proceed to _finalize_response normally.
    """
    async def __call__(self, ctx: CallbackContext, *, response: "AgentMessage") -> CallbackResult | None: ...


# ============ Callbacks Container ============


@dataclass
class RunnerCallbacks:
    """封装所有 hook 列表，注入到 AgentRunner。"""
    before_agent: list[BeforeAgentCallback] = field(default_factory=list)
    after_agent: list[AfterAgentCallback] = field(default_factory=list)
    before_model: list[BeforeModelCallback] = field(default_factory=list)
    after_model: list[AfterModelCallback] = field(default_factory=list)
    before_tool: list[BeforeToolCallback] = field(default_factory=list)
    after_tool: list[AfterToolCallback] = field(default_factory=list)
    before_loop_end: list[BeforeLoopEndCallback] = field(default_factory=list)
