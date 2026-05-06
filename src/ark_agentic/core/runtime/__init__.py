"""Core runtime — agent execution + always-on Lifecycle components.

Holds everything the framework needs at runtime to run agents:

- agent execution: ``BaseAgent`` (declarative + ReAct loop),
  ``AgentRegistry``, ``RunnerCallbacks``, ``IntakeGuard`` Protocol.
- the agents Lifecycle wrapper: ``AgentsLifecycle`` — Bootstrap
  auto-loads this alongside ``observability.TracingLifecycle``
  around the user-selectable plugins.

These are NOT plugins (not user-selectable). The Lifecycle wrapper
exists so Bootstrap can drive registration / warmup uniformly
alongside plugins.
"""

from .agents_lifecycle import AgentsLifecycle
from .base_agent import BaseAgent, RunnerConfig, RunResult
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
from .discovery import discover_agents
from .guard import GuardResult, IntakeGuard
from .registry import AgentRegistry

__all__ = [
    "AfterAgentCallback",
    "AfterModelCallback",
    "AfterToolCallback",
    "AgentRegistry",
    "AgentsLifecycle",
    "BaseAgent",
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
    "discover_agents",
    "merge_runner_callbacks",
]
