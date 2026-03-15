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
