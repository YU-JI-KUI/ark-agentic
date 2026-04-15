"""Agent data directory resolution."""

from __future__ import annotations

import os
from pathlib import Path


def prepare_agent_data_dir(agent_name: str) -> Path:
    """Resolve and create an agent-specific data directory.

    Resolution: SESSIONS_DIR env var / agent_name > data/ark_sessions/agent_name.
    """
    path = Path(os.getenv("SESSIONS_DIR") or "data/ark_sessions") / agent_name
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_memory_base_dir() -> Path:
    """Resolve the memory base directory.

    Resolution: MEMORY_DIR env var > data/ark_memory.
    """
    return Path(os.getenv("MEMORY_DIR") or "data/ark_memory")


def get_notifications_base_dir() -> Path:
    """Resolve the notifications base directory.

    Resolution: NOTIFICATIONS_DIR env var > data/ark_notifications.
    """
    return Path(os.getenv("NOTIFICATIONS_DIR") or "data/ark_notifications")
