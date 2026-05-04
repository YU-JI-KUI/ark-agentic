"""APIPlugin — built-in HTTP transport.

Owns the always-on chat router, /health, the AppContext infrastructure,
and the global HTTP middleware (CORS + a windows-probe drop). Headless
(CLI / worker) deployments simply omit this plugin and get no FastAPI
plumbing.
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
        from fastapi.middleware.cors import CORSMiddleware
        from fastapi.responses import Response

        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        # Windows Update / CryptSvc routes CRL fetches at any local
        # listener; silently drop them so they don't pollute access logs.
        @app.middleware("http")
        async def _drop_windows_update_probes(request, call_next):
            if "/msdownload/update/" in request.url.path:
                return Response(status_code=204)
            return await call_next(request)

        from . import chat
        app.include_router(chat.router)

        @app.get("/health")
        async def health_check():
            return {"status": "ok"}
