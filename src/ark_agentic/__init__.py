"""
ark-agentic - 轻量级 ReAct 智能体框架

顶层便捷导入，等价于 ``from ark_agentic.core import ...``。
完整 API 请参阅 ``ark_agentic.core`` 及其子模块。

## 快速开始

```python
from ark_agentic import BaseAgent

class MyAgent(BaseAgent):
    agent_id          = "my_agent"
    agent_name        = "My Agent"
    agent_description = "一个示例智能体"

    def build_tools(self):
        return []  # 返回业务工具列表


# 框架在 Bootstrap 启动时自动发现并实例化 BaseAgent 子类，
# 没有显式工厂函数也没有注册钩子。直接构造也可以：
agent = MyAgent()
session_id = await agent.create_session(user_id="default")
result = await agent.run(session_id, "你好", user_id="default")
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
    BaseAgent,
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
    # Agent
    "BaseAgent",
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
