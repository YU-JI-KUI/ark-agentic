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


def get_agents_root() -> Path:
    """Return the resolved agents root directory.

    ``Bootstrap`` writes ``AGENTS_ROOT`` to the environment during its
    init (resolved from explicit arg / env / caller-convention), so any
    downstream runtime code that needs the path (Studio's filesystem
    CRUD on user agents, meta_builder tools) sees the same value the
    discovery + lifecycle used.

    Raises:
        RuntimeError: if ``AGENTS_ROOT`` is unset. Bootstrap should run
        before any caller of this function; an unset value indicates a
        misconfigured deployment.
    """
    env = os.getenv("AGENTS_ROOT")
    if not env:
        raise RuntimeError(
            "AGENTS_ROOT is not set. Construct Bootstrap (which resolves "
            "and exports it) before calling get_agents_root(), or set the "
            "AGENTS_ROOT environment variable explicitly."
        )
    return Path(env).resolve()


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
