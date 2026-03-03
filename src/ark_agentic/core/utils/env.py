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


def resolve_agent_dir(agents_root: Path, agent_id: str) -> Path | None:
    """在 agents 根目录下解析 agent 子目录；不存在或非目录或路径穿越时返回 None。

    agent_id 须为 snake_case（如 meta_builder），与目录名一致；
    会先尝试 agent_id 再尝试 agent_id.replace("-", "_") 作为目录名以兼容旧 id。
    """
    root = Path(agents_root).resolve()
    if not agent_id or "/" in agent_id or "\\" in agent_id or agent_id in (".", ".."):
        return None
    for candidate in (agent_id, agent_id.replace("-", "_")):
        if candidate != agent_id and ("/" in candidate or "\\" in candidate):
            continue
        agent_dir = (root / candidate).resolve()
        if not agent_dir.is_dir():
            continue
        try:
            agent_dir.relative_to(root)
        except ValueError:
            continue
        return agent_dir
    return None
