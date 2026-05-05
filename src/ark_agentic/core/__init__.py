"""ark-agentic Core: ReAct Agent 框架

Public API surface — 外部项目应仅使用此模块及子模块 __all__ 中列出的符号。

子模块:
    core.runtime  — AgentRunner, AgentRegistry, RunnerCallbacks, AgentsLifecycle …
    core.observability — OTel decorators, tracing setup, TracingLifecycle
    core.session  — SessionManager, JSONL 编解码, 上下文压缩
    core.protocol — Lifecycle / Plugin / Bootstrap / AppContext
    core.tools   — AgentTool, ToolRegistry 等
    core.memory  — MemoryManager, Dream 等
    core.skills  — SkillLoader, SkillMatcher 等
    core.stream  — StreamAssembler, StreamEventBus 等
    core.prompt  — SystemPromptBuilder, PromptConfig
    core.llm     — create_chat_model, PAModel 等
"""

from .types import (
    AgentMessage,
    AgentToolResult,
    ToolCall,
    SessionEntry,
    SkillEntry,
    SkillMetadata,
    SkillLoadMode,
    TokenUsage,
    CompactionStats,
    MessageRole,
    ToolResultType,
    ToolLoopAction,
    ToolEvent,
    CustomToolEvent,
    UIComponentToolEvent,
    StepToolEvent,
    RunOptions,
)
from .runtime.callbacks import (
    CallbackContext,
    CallbackEvent,
    CallbackResult,
    HookAction,
    BeforeAgentCallback,
    AfterAgentCallback,
    BeforeModelCallback,
    AfterModelCallback,
    OnModelErrorCallback,
    BeforeToolCallback,
    AfterToolCallback,
    BeforeLoopEndCallback,
    RunnerCallbacks,
    merge_runner_callbacks,
)
from .runtime.runner import AgentRunner, RunnerConfig, RunResult
from .runtime.factory import AgentDef, build_standard_agent
from .session.manager import SessionManager
from .session.compaction import (
    ContextCompactor,
    CompactionConfig,
    CompactionResult,
    SummarizerProtocol,
    estimate_tokens,
    estimate_message_tokens,
)
from .session.format import RawJsonlValidationError
from .storage.entries import SessionStoreEntry
from .storage.repository.file._lock import FileLock
from .llm import (
    PAModel,
    PAModelConfig,
    create_chat_model,
    create_chat_model_from_env,
    LLMError,
    LLMErrorReason,
)
from .observability import (
    add_span_attributes,
    add_span_input,
    add_span_output,
    get_tracer,
    setup_tracing_from_env,
    shutdown_tracing,
    traced_agent,
    traced_chain,
    traced_tool,
)

__all__ = [
    # Types
    "AgentMessage",
    "AgentToolResult",
    "ToolCall",
    "SessionEntry",
    "SkillEntry",
    "SkillMetadata",
    "SkillLoadMode",
    "TokenUsage",
    "CompactionStats",
    "MessageRole",
    "ToolResultType",
    "ToolLoopAction",
    "ToolEvent",
    "CustomToolEvent",
    "UIComponentToolEvent",
    "StepToolEvent",
    "RunOptions",
    # Callbacks
    "CallbackContext",
    "CallbackEvent",
    "CallbackResult",
    "HookAction",
    "BeforeAgentCallback",
    "AfterAgentCallback",
    "BeforeModelCallback",
    "AfterModelCallback",
    "OnModelErrorCallback",
    "BeforeToolCallback",
    "AfterToolCallback",
    "BeforeLoopEndCallback",
    "RunnerCallbacks",
    "merge_runner_callbacks",
    # Runner
    "AgentRunner",
    "RunnerConfig",
    "RunResult",
    # Agent factory
    "AgentDef",
    "build_standard_agent",
    # Session
    "SessionManager",
    # Compaction
    "ContextCompactor",
    "CompactionConfig",
    "CompactionResult",
    "SummarizerProtocol",
    "estimate_tokens",
    "estimate_message_tokens",
    # Persistence
    "SessionStoreEntry",
    "FileLock",
    "RawJsonlValidationError",
    # LLM
    "PAModel",
    "PAModelConfig",
    "create_chat_model",
    "create_chat_model_from_env",
    "LLMError",
    "LLMErrorReason",
    # Observability
    "add_span_attributes",
    "add_span_input",
    "add_span_output",
    "get_tracer",
    "setup_tracing_from_env",
    "shutdown_tracing",
    "traced_agent",
    "traced_chain",
    "traced_tool",
]
