"""
环境与路径工具，用于提取整个工程中重复判断的系统级配置。
"""

import os
from pathlib import Path


def get_agents_root(current_file: str | Path) -> Path:
    """获取 agents/ 根目录路径，解决多文件重复 _agents_root() 的问题。

    优先级:
      1. 环境变量 AGENTS_ROOT (明确配置，适合线上部署)
      2. 从给定的 current_file 向上遍历寻找 pyproject.toml 所在的 src/ark_agentic/agents
      3. 回退策略：简单向上找 4 层 (适用于一般源码目录结构)
    """
    if env_root := os.getenv("AGENTS_ROOT"):
        return Path(env_root).resolve()

    cursor = Path(current_file).resolve().parent
    for _ in range(10):
        if (cursor / "pyproject.toml").exists():
            project_agents = cursor / "src" / "ark_agentic" / "agents"
            if project_agents.is_dir():
                return project_agents
            fallback_agents = cursor / "agents"
            if fallback_agents.is_dir():
                return fallback_agents
            break
        if cursor == cursor.parent:
            break
        cursor = cursor.parent

    # 作为最终 fallback
    return Path(current_file).resolve().parents[4]
