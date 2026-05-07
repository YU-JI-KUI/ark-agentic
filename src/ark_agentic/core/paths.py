"""Agent data directory resolution."""

from __future__ import annotations

import os
from pathlib import Path


def prepare_agent_data_dir(agent_name: str) -> Path:
    """Resolve and create an agent-specific data directory.

    Resolution: SESSIONS_DIR env var / agent_name, otherwise
    data/ark_sessions/agent_name.
    """
    path = Path(os.getenv("SESSIONS_DIR") or "data/ark_sessions") / agent_name
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_memory_base_dir() -> Path:
    """Resolve the memory base directory.

    Resolution: MEMORY_DIR env var > data/ark_memory.
    """
    return Path(os.getenv("MEMORY_DIR") or "data/ark_memory")


def get_config_base_dir() -> Path:
    """Resolve the agent config base directory.

    Resolution: CONFIG_DIR env var > data/ark_config.
    """
    return Path(os.getenv("CONFIG_DIR") or "data/ark_config")


def get_agent_config_dir(agent_name: str, *, create: bool = False) -> Path:
    """Resolve an agent-specific config directory."""
    path = get_config_base_dir() / _safe_agent_name(agent_name)
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def get_agent_config_file(agent_name: str, *, create: bool = False) -> Path:
    """Resolve ``agent.json`` for one agent under ``CONFIG_DIR``."""
    return get_agent_config_dir(agent_name, create=create) / "agent.json"


def resolve_agent_config_file(
    agent_name: str,
    *,
    legacy_agent_dir: Path | None = None,
) -> Path | None:
    """Find ``agent.json`` from CONFIG_DIR first, then legacy agent dir."""
    config_file = get_agent_config_file(agent_name)
    if config_file.is_file():
        return config_file
    if legacy_agent_dir is not None:
        legacy_file = legacy_agent_dir / "agent.json"
        if legacy_file.is_file():
            return legacy_file
    return None


def _safe_agent_name(agent_name: str) -> str:
    if (
        not agent_name
        or "/" in agent_name
        or "\\" in agent_name
        or agent_name in {".", ".."}
    ):
        raise ValueError(f"Invalid agent name: {agent_name!r}")
    return agent_name
