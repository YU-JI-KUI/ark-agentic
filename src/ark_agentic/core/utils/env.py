"""
环境与路径工具，用于提取整个工程中重复判断的系统级配置。
"""

import os
from pathlib import Path


def env_flag(name: str, *, default: bool = False) -> bool:
    """Truthy-string env-var read. Empty / unset → ``default``.

    Truthy values (case-insensitive): ``"true"`` / ``"1"``.
    """
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return raw.lower() in ("true", "1")


def get_agents_root(current_file: str | Path) -> Path:
    """获取 agents/ 根目录路径，解决多文件重复 _agents_root() 的问题。

    优先级:
      1. 环境变量 AGENTS_ROOT (明确配置，适合线上部署)
      2. 从给定的 current_file 向上遍历寻找 pyproject.toml 所在的项目根；
         在 ``src/<pkg>/agents`` 中匹配第一个存在的 ``<pkg>``
         (按字典序，确定性)。这覆盖框架自身的 ``src/ark_agentic/agents``，
         也覆盖 wheel 消费者的 ``src/<their_pkg>/agents``。
      3. 回退策略：简单向上找 4 层 (适用于一般源码目录结构)
    """
    if env_root := os.getenv("AGENTS_ROOT"):
        return Path(env_root).resolve()

    cursor = Path(current_file).resolve().parent
    for _ in range(10):
        if (cursor / "pyproject.toml").exists():
            src_dir = cursor / "src"
            if src_dir.is_dir():
                for pkg_dir in sorted(src_dir.iterdir()):
                    candidate = pkg_dir / "agents"
                    if candidate.is_dir():
                        return candidate
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
