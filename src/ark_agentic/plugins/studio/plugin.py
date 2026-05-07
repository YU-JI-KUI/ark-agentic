"""StudioPlugin — optional admin console.

Mounts every Studio API router + the React frontend dist (when built).
``init_schema`` bootstraps Studio Auth using the active storage mode.
"""

from __future__ import annotations

from typing import Any

from ...core.protocol.plugin import BasePlugin
from ...core.utils.env import env_flag


class StudioPlugin(BasePlugin):
    name = "studio"

    def is_enabled(self) -> bool:
        return env_flag("ENABLE_STUDIO")

    async def init(self) -> None:
        from .services.auth.engine import init_schema
        await init_schema()

    def install_routes(self, app: Any) -> None:
        # Studio used to also auto-register the meta_builder agent.
        # That responsibility now lives in agents/meta_builder/__init__.py
        # and runs through agents.register_all — independent of Studio.
        from . import setup_studio
        setup_studio(app, registry=None)
