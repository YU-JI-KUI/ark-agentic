"""APIPlugin — built-in HTTP transport for the chat API.

Owns the always-on chat router plus the surrounding HTTP plumbing it
needs to be usable: ``/health``, the global middleware (CORS + a
Windows-Update probe drop). Nothing else.

Headless (CLI / worker) deployments simply omit this plugin and get no
FastAPI plumbing.

Note: this plugin no longer mounts ``/`` or ``/api/static``. The wheel
ships no demo page; CLI-scaffolded projects bundle their own
``static/index.html`` and mount it from their own ``app.py`` (see
``ark-agentic init`` template). Framework-internal demos are served by
the ``Portal`` lifecycle on the developer checkout.
"""

from __future__ import annotations

from typing import Any

from ...core.protocol.plugin import BasePlugin
from ...core.utils.env import env_flag


class APIPlugin(BasePlugin):
    name = "api"

    def is_enabled(self) -> bool:
        # API is opt-out (default on); set ENABLE_API=false to disable
        # for headless / CLI-only / worker-only deployments.
        return env_flag("ENABLE_API", default=True)

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
