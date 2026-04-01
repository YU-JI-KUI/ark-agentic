---
name: running-tests
description: Use when running tests in ark-agentic project - provides pytest commands and environment setup
---

# Running Tests

## Overview

ark-agentic 项目的测试运行指南。

## Basic Commands

```bash
# 运行所有测试
uv run pytest -v

# 运行特定测试文件
uv run pytest tests/core/test_runner.py -v

# 运行特定测试
uv run pytest tests/core/test_runner.py::test_function_name -v
```

## Environment Variables

```bash
# Mock模式（不需要真实API）
SECURITIES_SERVICE_MOCK=true uv run pytest tests/agents/securities/ -v

# LLM集成测试（需要API Key）
export DEEPSEEK_API_KEY=sk-xxx
uv run pytest tests/core/test_compaction.py -v
```

## Test Categories

| 目录 | 说明 |
|------|------|
| `tests/core/` | 核心模块测试 |
| `tests/agents/` | 智能体测试 |
| `tests/integration/` | 集成测试 |

## Quick Reference

```bash
# 核心测试
uv run pytest tests/core/ -v

# 证券智能体测试
SECURITIES_SERVICE_MOCK=true uv run pytest tests/agents/securities/ -v

# 集成测试
SECURITIES_SERVICE_MOCK=true uv run pytest tests/test_context_injection.py -v
```