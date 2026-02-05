"""
ark-agentic Core - 智能体核心框架

基于 ReAct 模式的轻量级智能体框架。

## 核心组件

- **types**: 核心类型定义 (AgentMessage, ToolCall, SessionEntry 等)
- **runner**: 智能体执行器 (AgentRunner)
- **session**: 会话管理 (SessionManager)
- **tools**: 工具系统 (AgentTool, ToolRegistry)
- **skills**: 技能系统 (SkillLoader, SkillMatcher)
- **compaction**: 上下文压缩
- **stream**: 流式输出处理
- **prompt**: 系统提示构建
- **llm**: LLM 客户端

## 快速开始

```python
from ark_agentic.core import AgentRunner, ToolRegistry, SessionManager, create_llm_client

# 创建 LLM 客户端
llm_client = create_llm_client("deepseek", api_key="sk-xxx")

# 创建组件
tool_registry = ToolRegistry()
session_manager = SessionManager()
runner = AgentRunner(llm_client, tool_registry, session_manager)

# 运行
session_id = await runner.create_session()
result = await runner.run(session_id, "用户输入")
```
"""

from .types import (
    AgentMessage,
    AgentToolResult,
    ToolCall,
    SessionEntry,
    SkillEntry,
    SkillMetadata,
    TokenUsage,
    CompactionStats,
    MessageRole,
    ToolResultType,
)
from .runner import AgentRunner, RunnerConfig, RunResult
from .session import SessionManager
from .compaction import (
    ContextCompactor,
    CompactionConfig,
    CompactionResult,
    estimate_tokens,
    estimate_message_tokens,
)
from .persistence import (
    TranscriptManager,
    SessionStore,
    SessionStoreEntry,
    FileLock,
)
from .llm import (
    LLMClientProtocol,
    LLMConfig,
    create_llm_client,
    OpenAICompatibleClient,
    InternalAPIClient,
)

__all__ = [
    # Types
    "AgentMessage",
    "AgentToolResult",
    "ToolCall",
    "SessionEntry",
    "SkillEntry",
    "SkillMetadata",
    "TokenUsage",
    "CompactionStats",
    "MessageRole",
    "ToolResultType",
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
    "estimate_tokens",
    "estimate_message_tokens",
    # Persistence
    "TranscriptManager",
    "SessionStore",
    "SessionStoreEntry",
    "FileLock",
    # LLM
    "LLMClientProtocol",
    "LLMConfig",
    "create_llm_client",
    "OpenAICompatibleClient",
    "InternalAPIClient",
]
