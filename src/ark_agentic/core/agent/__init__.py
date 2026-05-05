"""Agent execution machinery — runner, factory, registry, callbacks, guards.

The ReAct loop runner (``runner.py``), agent builder (``factory.py``),
runtime registry (``registry.py``), runner-level callback hooks
(``callbacks.py``), intake guard Protocol (``guard.py``), and citation
grounding callback (``validation.py``).

Distinct from the framework's ``core.runtime`` package — that one holds
always-on Lifecycle implementations that wrap *this* execution layer
into the app start/stop sequence.
"""

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
