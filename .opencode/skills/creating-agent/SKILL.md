---
name: creating-agent
description: Use when creating a new agent in ark-agentic framework - guides agent structure, tools, and skills setup
---

# Creating Agent

## Overview

在 ark-agentic 框架中创建新的业务智能体。

## When to Use

- 需要创建新的业务智能体
- 需要为新领域添加agent实现
- 需要扩展现有agent功能

## Directory Structure

```
src/ark_agentic/agents/<agent-name>/
├── __init__.py           # 导出
├── agent.py              # AgentRunner 配置
├── api.py                # 工厂函数
├── tools/                # 业务工具
│   ├── __init__.py
│   └── <tool_name>.py
└── skills/               # 业务技能
    └── <skill_name>/
        └── SKILL.md
```

## Quick Steps

1. 创建目录结构
2. 实现工具类（继承 AgentTool）
3. 创建技能文件（SKILL.md）
4. 编写工厂函数
5. 添加测试

## Example Tool

```python
from ark_agentic.core.tools.base import AgentTool, ToolResult

class MyTool(AgentTool):
    name = "my_tool"
    description = "工具描述"
    
    async def _run(self, param: str) -> ToolResult:
        return ToolResult(type="TEXT", content=f"结果: {param}")
```

## Reference

参考现有实现：
- `src/ark_agentic/agents/insurance/` - 保险智能体
- `src/ark_agentic/agents/securities/` - 证券智能体