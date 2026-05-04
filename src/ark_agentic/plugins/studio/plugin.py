"""StudioPlugin — optional admin console.

Mounts every Studio API router + the React frontend dist (when built).
``init_schema`` runs against Studio's dedicated SQLite engine regardless
of DB_TYPE since it has its own ``AuthBase`` independent of core tables.
"""

from __future__ import annotations

import os
from typing import Any

from ...core.plugin import BasePlugin


class StudioPlugin(BasePlugin):
    name = "studio"

    def is_enabled(self) -> bool:
        return os.getenv("ENABLE_STUDIO", "").lower() == "true"

    async def init_schema(self) -> None:
        from .services.auth.engine import init_schema
        await init_schema()

    def install_routes(self, app: Any) -> None:
        # Studio used to also auto-register the meta_builder agent.
        # That responsibility now lives in agents/meta_builder/__init__.py
        # and runs through agents.register_all — independent of Studio.
        from . import setup_studio
        setup_studio(app, registry=None)
