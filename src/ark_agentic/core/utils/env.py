"""
环境与路径工具，用于提取整个工程中重复判断的系统级配置。
"""

import json
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
    """解析 agent_id 对应的真实目录路径。"""
    if not agents_root.is_dir():
        return None
    
    # 1. 优先认为目录同名（例如 id="insurance" -> dir="insurance"）
    target = agents_root / agent_id
    if target.is_dir():
        return target
    
    # 2. 破折号替换为下划线尝试（例如 id="meta-builder" -> dir="meta_builder"）
    target = agents_root / agent_id.replace("-", "_")
    if target.is_dir():
        return target
    
    # 3. 扫描 agent.json 中的 id 字段
    for child in agents_root.iterdir():
        if child.is_dir() and not child.name.startswith(("_", ".")):
            meta_file = child / "agent.json"
            if meta_file.is_file():
                try:
                    data = json.loads(meta_file.read_text(encoding="utf-8"))
                    if data.get("id") == agent_id:
                        return child
                except Exception:
                    pass
    return None
