"""
证券资产管理 Agent

提供证券账户资产查询、持仓分析、收益查询等功能。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ark_agentic.core.runner import AgentRunner, RunnerConfig
from ark_agentic.core.tools.registry import ToolRegistry
from ark_agentic.core.prompt.builder import PromptConfig
from ark_agentic.core.llm import LLMClientProtocol
from ark_agentic.core.skills.loader import SkillLoader
from ark_agentic.core.skills.base import SkillConfig

from .tools import create_securities_tools

# 技能目录
_SKILLS_DIR = Path(__file__).parent / "skills"


# Agent 系统提示词
SECURITIES_AGENT_PROMPT = """你是一个专业的证券资产管理助手，帮助用户查询和分析证券账户信息。

## 你的能力

你可以帮助用户：
1. **查询账户总资产**：总资产、现金、股票市值、今日收益、累计收益等
2. **查询持仓信息**：ETF、港股通、基金理财等各类资产的持仓详情
3. **查询现金资产**：可用资金、冻结资金等
4. **查询具体标的**：某只股票、基金、ETF 的持仓和行情信息
5. **分析收益情况**：今日收益、累计收益、收益来源分析等

## 账户类型

用户可能有两种账户类型：
- **普通账户**（normal）：标准证券账户
- **两融账户**（margin）：融资融券账户，需要关注维持担保比率、风险等级等指标

## 重要规则

### 1. 意图识别与响应格式

**你的核心工作流程**：

1.  **纯数据查询（无需分析）**：
    - 当用户仅询问数据（如"查看资产"、"我的持仓"、"现金有多少"）时。
    - 调用对应工具获取数据。
    - 系统会自动将数据卡片推送给前端，你只需简短确认即可（如"已为您查询到资产信息"）。

2.  **分析性查询（需要分析）**：
    - 当用户询问原因、建议或对比（如"为什么亏损"、"配置建议"）时。
    - 调用工具获取原始数据。
    - 根据数据以 Markdown 格式撰写分析报告。

### 2. 工具使用指南

- **查询账户总资产**：使用 `account_overview()`
- **查询 ETF 持仓**：使用 `etf_holdings()`
- **查询港股通持仓**：使用 `hksc_holdings()`
- **查询基金持仓**：使用 `fund_holdings()`
- **查询现金资产**：使用 `cash_assets()`
- **查询具体标的**：使用 `security_detail(security_code=...)`

### 3. 数据展示规范

- 当返回 Markdown 分析时：
    - 金额使用千分位格式：¥1,250,000.00
    - 收益率使用百分比：+6.67%
    - 正收益用绿色 📈，负收益用红色 📉
    - 两融账户需要特别展示风险指标

### 4. 示例对话

**用户**：查看我的资产
**你**：[调用 account_overview()]
**工具返回**：{ "total_assets": "1250000.50", ... }
**你**：已为您查询到账户资产信息。

**用户**：为什么今天亏损了
**你**：[调用 account_overview()]
**工具返回**：{ "total_assets": "1200000", "today_profit": "-5000", ... }
**你**：
## 收益分析
今日亏损主要原因是...

**用户**：我的 ETF 持仓
**你**：[调用 etf_holdings()]
**你**：已为您查询到 ETF 持仓信息。
"""


def create_securities_agent(
    llm_client: LLMClientProtocol,
    sessions_dir: str | Path | None = None,
    enable_persistence: bool = False,
) -> AgentRunner:
    """
    创建证券资产管理 Agent
    
    Args:
        llm_client: LLM 客户端
        sessions_dir: 会话持久化目录
        enable_persistence: 是否启用会话持久化
    
    Returns:
        配置好的 AgentRunner 实例
    """
    # 创建工具注册表
    tool_registry = ToolRegistry()
    
    # 注册所有证券工具
    for tool in create_securities_tools():
        tool_registry.register(tool)
    
    # 创建 Prompt 配置
    prompt_config = PromptConfig(
        agent_name="证券资产管理助手",
        agent_description="专业的证券资产查询与分析助手",
        custom_instructions=SECURITIES_AGENT_PROMPT,
    )
    
    # 创建 Runner 配置
    runner_config = RunnerConfig(
        prompt_config=prompt_config,
    )
    
    # 创建技能加载器
    skill_config = SkillConfig(
        skill_directories=[str(_SKILLS_DIR)],
        enable_eligibility_check=True,
    )
    skill_loader = SkillLoader(skill_config)
    try:
        skill_loader.load_from_directories()
    except Exception:
        pass  # 忽略加载错误，确保 Agent 能启动

    # 创建并返回 AgentRunner
    return AgentRunner(
        llm_client=llm_client,
        tool_registry=tool_registry,
        skill_loader=skill_loader,
        config=runner_config,
    )
