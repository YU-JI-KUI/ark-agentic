"""
ark-agentic - 轻量级 ReAct 智能体框架

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
    create_llm_client,
    LLMClientProtocol,
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
    "create_llm_client",
    "LLMClientProtocol",
    # Tools
    "AgentTool",
    "ToolParameter",
    "ToolRegistry",
]
