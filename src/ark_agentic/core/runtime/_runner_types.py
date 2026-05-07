"""Per-call execution data carriers for ``BaseAgent``.

Pure data — no behavior, no I/O. Lives separately from ``base_agent.py``
so the BaseAgent module stays focused on agent identity + execution
orchestration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, NamedTuple

from ..llm.sampling import SamplingConfig
from ..prompt.builder import PromptConfig
from ..skills.base import SkillConfig
from ..skills.router import SkillRouter
from ..types import AgentMessage, AgentToolResult, ToolCall


@dataclass
class RunnerConfig:
    """Per-call execution knobs. Identity / tools / skills live on BaseAgent."""

    model: str | None = None
    sampling: SamplingConfig = field(default_factory=SamplingConfig.for_chat)
    max_retries: int = 3
    max_turns: int = 10
    max_tool_calls_per_turn: int = 5
    tool_timeout: float = 30.0
    auto_compact: bool = True
    prompt_config: PromptConfig = field(default_factory=PromptConfig)
    skill_config: SkillConfig = field(default_factory=SkillConfig)
    enable_subtasks: bool = False
    accept_external_history: bool = True
    skill_router: SkillRouter | None = None


@dataclass
class RunResult:
    """ReAct loop result returned to callers."""

    response: AgentMessage
    turns: int = 0
    tool_calls_count: int = 0
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[AgentToolResult] = field(default_factory=list)
    stopped_by_limit: bool = False


class _RunParams(NamedTuple):
    """Resolved per-run parameters (pure computation result)."""

    model: str | None
    sampling_override: SamplingConfig | None
    skill_load_mode: str


@dataclass
class _LoopState:
    """ReAct loop accumulator (private)."""

    turns: int = 0
    total_tool_calls: int = 0
    all_tool_calls: list[ToolCall] = field(default_factory=list)
    all_tool_results: list[AgentToolResult] = field(default_factory=list)

    def make_result(self, response: AgentMessage, **overrides: Any) -> RunResult:
        return RunResult(
            response=response,
            turns=self.turns,
            tool_calls_count=self.total_tool_calls,
            tool_calls=self.all_tool_calls,
            tool_results=self.all_tool_results,
            **overrides,
        )
