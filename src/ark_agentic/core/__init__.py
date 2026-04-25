"""ark-agentic Core: ReAct Agent 框架

Public API surface — 外部项目应仅使用此模块及子模块 __all__ 中列出的符号。

子模块:
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
from .callbacks import (
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
from .runner import AgentRunner, RunnerConfig, RunResult
from .session import SessionManager
from .compaction import (
    ContextCompactor,
    CompactionConfig,
    CompactionResult,
    SummarizerProtocol,
    estimate_tokens,
    estimate_message_tokens,
)
from .persistence import (
    TranscriptManager,
    SessionStore,
    SessionStoreEntry,
    FileLock,
    RawJsonlValidationError,
)
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
    "TranscriptManager",
    "SessionStore",
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
