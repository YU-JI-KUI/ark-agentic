"""APIPlugin — built-in HTTP transport (chat endpoints + AppContext).

The API plugin owns the always-on chat router and the typed
``AppContext`` infrastructure that other plugins consume. CLI-only or
worker-only deployments can omit it entirely; deployments that mount
this plugin get a FastAPI app with /chat plus whatever other plugins
register routes through ``install_routes``.
"""

from __future__ import annotations

import os
from typing import Any

from ...core.plugin import BasePlugin


def _env_flag(name: str, default: str = "true") -> bool:
    return os.getenv(name, default).lower() in ("true", "1")


class APIPlugin(BasePlugin):
    name = "api"

    def is_enabled(self) -> bool:
        # API is opt-out (default on); set ENABLE_API=false to disable
        # for headless / CLI-only / worker-only deployments.
        return _env_flag("ENABLE_API", default="true")

    def install_routes(self, app: Any) -> None:
        from . import chat
        app.include_router(chat.router)

        @app.get("/health")
        async def health_check():
            return {"status": "ok"}
