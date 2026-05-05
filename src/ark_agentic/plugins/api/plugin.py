"""APIPlugin — built-in HTTP transport for the chat API.

Owns the always-on chat router plus the surrounding HTTP plumbing it
needs to be usable: ``/health``, the global middleware (CORS +
a windows-probe drop), and a default ``/`` chat-demo page so end-users
get something usable as soon as they enable the plugin.

Scope is intentionally narrow — chat transport only. App-level state
(``AppContext``) lives in ``core``; other plugins own their own routes
and do not depend on this one.

Headless (CLI / worker) deployments simply omit this plugin and get no
FastAPI plumbing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ...core.protocol.plugin import BasePlugin
from ...core.utils.env import env_flag

_STATIC_DIR = Path(__file__).parent / "static"


class APIPlugin(BasePlugin):
    name = "api"

    def is_enabled(self) -> bool:
        # API is opt-out (default on); set ENABLE_API=false to disable
        # for headless / CLI-only / worker-only deployments.
        return env_flag("ENABLE_API", default=True)

    async def start(self, ctx: Any) -> None:
        # Wire the legacy ``deps`` singleton from the registry that
        # AgentsLifecycle published on the context. AgentsLifecycle
        # always starts before APIPlugin so ctx.agent_registry is set.
        from . import deps
        deps.init_registry(ctx.agent_registry)

    def install_routes(self, app: Any) -> None:
        from fastapi.middleware.cors import CORSMiddleware
        from fastapi.responses import FileResponse, Response
        from fastapi.staticfiles import StaticFiles

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

        # Default chat-demo page. The framework's own deployment may
        # register a different ``/`` handler before this plugin's
        # install_routes runs (registration order wins in Starlette);
        # third-party deployments without that override see this page.
        if _STATIC_DIR.is_dir():
            app.mount(
                "/api/static",
                StaticFiles(directory=str(_STATIC_DIR)),
                name="api-static",
            )

            @app.get("/", include_in_schema=False)
            async def _index():
                return FileResponse(
                    str(_STATIC_DIR / "index.html"),
                    media_type="text/html",
                )
