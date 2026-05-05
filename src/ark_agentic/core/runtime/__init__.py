"""Core runtime — agent execution + always-on Lifecycle components.

Holds everything the framework needs at runtime to run agents:

- agent execution: ``AgentRunner`` (ReAct loop), ``AgentRegistry``,
  ``RunnerCallbacks`` (per-call hooks), ``IntakeGuard`` Protocol,
  the citation/grounding callback, and ``build_standard_agent``.
- the agents Lifecycle wrapper: ``AgentsLifecycle`` — Bootstrap
  auto-loads this alongside ``observability.TracingLifecycle``
  around the user-selectable plugins.

These are NOT plugins (not user-selectable). The Lifecycle wrapper
exists so Bootstrap can drive registration / warmup uniformly
alongside plugins.
"""

from .agents_lifecycle import AgentsLifecycle
from .callbacks import (
    AfterAgentCallback,
    AfterModelCallback,
    AfterToolCallback,
    BeforeAgentCallback,
    BeforeLoopEndCallback,
    BeforeModelCallback,
    BeforeToolCallback,
    CallbackContext,
    CallbackEvent,
    CallbackResult,
    HookAction,
    OnModelErrorCallback,
    RunnerCallbacks,
    merge_runner_callbacks,
)
from .factory import AgentDef, build_standard_agent
from .guard import GuardResult, IntakeGuard
from .registry import AgentRegistry
from .runner import AgentRunner, RunnerConfig, RunResult

__all__ = [
    "AfterAgentCallback",
    "AfterModelCallback",
    "AfterToolCallback",
    "AgentDef",
    "AgentRegistry",
    "AgentRunner",
    "AgentsLifecycle",
    "BeforeAgentCallback",
    "BeforeLoopEndCallback",
    "BeforeModelCallback",
    "BeforeToolCallback",
    "CallbackContext",
    "CallbackEvent",
    "CallbackResult",
    "GuardResult",
    "HookAction",
    "IntakeGuard",
    "OnModelErrorCallback",
    "RunResult",
    "RunnerCallbacks",
    "RunnerConfig",
    "build_standard_agent",
    "merge_runner_callbacks",
]
