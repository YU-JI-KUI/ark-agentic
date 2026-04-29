"""
agent_factory — 创建用于评测的隔离 agent 实例

通过环境变量注入临时 data 目录，确保每次评测使用全新的 session/memory，
不污染也不依赖 data/ 目录下的生产数据。
"""

from __future__ import annotations

import os
from pathlib import Path

from ark_agentic.core.runner import AgentRunner


def create_eval_agent(agent_name: str, data_dir: Path) -> AgentRunner:
    """创建隔离 data 目录的评测用 agent。

    Args:
        agent_name : "insurance" 或 "securities"
        data_dir   : 临时 data 根目录（由 pytest tmp_path fixture 提供）

    Returns:
        AgentRunner 实例（memory 关闭，不产生持久化副作用）
    """
    os.environ["SESSIONS_DIR"] = str(data_dir / "sessions")
    os.environ["MEMORY_DIR"] = str(data_dir / "memory")

    if agent_name == "insurance":
        from ark_agentic.agents.insurance import create_insurance_agent
        return create_insurance_agent(enable_memory=False, enable_dream=False)

    if agent_name == "securities":
        from ark_agentic.agents.securities import create_securities_agent
        return create_securities_agent(enable_memory=False, enable_dream=False)

    raise ValueError(f"未知 agent: {agent_name!r}，支持: insurance, securities")
