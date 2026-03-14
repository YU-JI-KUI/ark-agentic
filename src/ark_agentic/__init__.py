"""
ark-agentic - 轻量级 ReAct 智能体框架

顶层便捷导入，等价于 ``from ark_agentic.core import ...``。
完整 API 请参阅 ``ark_agentic.core`` 及其子模块。

## 快速开始

```python
from ark_agentic import AgentRunner, RunnerConfig, create_chat_model
from ark_agentic.core.tools import AgentTool, ToolRegistry
from ark_agentic.core.session import SessionManager

llm = create_chat_model(model="PA-JT-80B", api_key="sk-xxx")
runner = AgentRunner(llm, ToolRegistry())
session_id = await runner.create_session(user_id="default")
result = await runner.run(session_id, "你好", user_id="default")
```

## 模块结构

- ``ark_agentic.core``       — 核心框架
- ``ark_agentic.core.tools``  — 工具系统
- ``ark_agentic.core.memory`` — 记忆系统
- ``ark_agentic.core.skills`` — 技能系统
- ``ark_agentic.core.stream`` — 流式输出
- ``ark_agentic.core.prompt`` — 提示词构建
- ``ark_agentic.core.llm``    — LLM 适配层
"""

__version__ = "0.1.0"

from .core import (
    AgentRunner,
    RunnerConfig,
    RunResult,
    RunOptions,
    SessionManager,
    AgentMessage,
    ToolCall,
    MessageRole,
    SkillLoadMode,
    PAModel,
    create_chat_model,
    create_chat_model_from_env,
    CompactionConfig,
    ContextCompactor,
    LLMError,
)
from .core.tools.base import AgentTool, ToolParameter
from .core.tools.registry import ToolRegistry

__all__ = [
    "__version__",
    # Runner
    "AgentRunner",
    "RunnerConfig",
    "RunResult",
    "RunOptions",
    # Session
    "SessionManager",
    # Types
    "AgentMessage",
    "ToolCall",
    "MessageRole",
    "SkillLoadMode",
    # LLM
    "PAModel",
    "create_chat_model",
    "create_chat_model_from_env",
    "LLMError",
    # Tools
    "AgentTool",
    "ToolParameter",
    "ToolRegistry",
    # Compaction
    "CompactionConfig",
    "ContextCompactor",
]
