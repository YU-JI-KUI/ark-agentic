"""
ark-agentic - 轻量级 ReAct 智能体框架

## 快速开始

```python
from ark_agentic.core.llm import create_chat_model, PAModel

# 创建 LLM
llm = create_chat_model(model=PAModel.PA_SX_80B)

# 创建组件
from ark_agentic.core.runner import AgentRunner
from ark_agentic.core.tools.registry import ToolRegistry

tool_registry = ToolRegistry()
runner = AgentRunner(llm, tool_registry)

# 运行
session_id = await runner.create_session()
result = await runner.run(session_id, "用户输入")
```

## 模块结构

- `ark_agentic.core`: 核心框架（AgentRunner, SessionManager, ToolRegistry 等）
- `ark_agentic.agents`: 业务智能体实现
"""

__version__ = "0.1.0"

# 便捷导入
from .core import (
    AgentRunner,
    RunnerConfig,
    RunResult,
    SessionManager,
    AgentMessage,
    ToolCall,
    PAModel,
    create_chat_model,
)
from .core.tools.base import AgentTool, ToolParameter
from .core.tools.registry import ToolRegistry

__all__ = [
    # Version
    "__version__",
    # Core
    "AgentRunner",
    "RunnerConfig",
    "RunResult",
    "SessionManager",
    "AgentMessage",
    "ToolCall",
    # LLM
    "PAModel",
    "create_chat_model",
    # Tools
    "AgentTool",
    "ToolParameter",
    "ToolRegistry",
]
