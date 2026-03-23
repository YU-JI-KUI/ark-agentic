---
name: code-style
description: Use when writing or reviewing code in ark-agentic - defines formatting, imports, and patterns
---

# Code Style

## Overview

ark-agentic 项目的代码风格规范。

## Formatting

- 使用 `ruff` 进行代码格式化和lint
- Python 3.12+ 语法
- 类型注解必须

## Imports

```python
# 标准库
import os
import sys

# 第三方库
from fastapi import FastAPI
from langchain_core.messages import HumanMessage

# 本地模块
from ark_agentic.core.types import AgentState
```

## Type Annotations

```python
async def run(self, session_id: str, message: str) -> dict[str, Any]:
    ...

def create_tools() -> list[AgentTool]:
    ...
```

## Docstrings

- 类和公共函数必须有docstring
- 使用中文注释

## Key Patterns

| 模式 | 说明 |
|------|------|
| `AgentTool` | 工具基类 |
| `ToolResult` | 工具返回类型 |
| `SessionManager` | 会话管理 |
| `AgentRunner` | ReAct主循环 |

## Commands

```bash
# 格式化
uv run ruff format .

# Lint
uv run ruff check .

# 类型检查
uv run mypy src/
```