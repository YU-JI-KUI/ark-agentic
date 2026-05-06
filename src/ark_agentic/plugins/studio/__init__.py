"""
Ark-Agentic Studio — 可选管理控制台

通过环境变量 ENABLE_STUDIO=true 激活。
提供 Agent/Skill/Tool/Session 的可视化管理界面。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

if TYPE_CHECKING:
    from ark_agentic.core.runtime.registry import AgentRegistry

logger = logging.getLogger(__name__)

_FRONTEND_DIST = Path(__file__).parent / "frontend" / "dist"


def setup_studio(app: FastAPI, registry: AgentRegistry | None = None) -> None:
    """挂载 Studio 路由 + 前端静态文件。

    ``registry`` 参数保留但不再使用（之前 Studio 在此自动注册 meta_builder；
    该职责现在由 ``agents.register_all`` 统一接管，与 Studio 独立）。
    """
    del registry  # kept for API compatibility; meta_builder is auto-registered

    from .api import agents as agents_api
    from .api import auth as auth_api
    from .api import config as config_api
    from .api import dashboard as dashboard_api
    from .api import skills as skills_api
    from .api import tools as tools_api
    from .api import sessions as sessions_api
    from .api import memory as memory_api
    from .api import users as users_api

    # 挂载 Studio API 路由
    app.include_router(auth_api.router, prefix="/api/studio", tags=["studio"])
    app.include_router(users_api.router, prefix="/api/studio", tags=["studio"])
    app.include_router(agents_api.router, prefix="/api/studio", tags=["studio"])
    app.include_router(skills_api.router, prefix="/api/studio", tags=["studio"])
    app.include_router(tools_api.router, prefix="/api/studio", tags=["studio"])
    app.include_router(sessions_api.router, prefix="/api/studio", tags=["studio"])
    app.include_router(memory_api.router, prefix="/api/studio", tags=["studio"])
    app.include_router(dashboard_api.router, prefix="/api/studio", tags=["studio"])
    app.include_router(config_api.router, prefix="/api/studio", tags=["studio"])

    # 挂载前端静态资源（如果 build 产物存在）
    if _FRONTEND_DIST.is_dir():
        # 首先服务具体的静态文件 (js, css, assets)
        app.mount(
            "/studio/assets",
            StaticFiles(directory=str(_FRONTEND_DIST / "assets")),
            name="studio-assets",
        )
        
        # 为了支持 React Router (SPA)，必须使用通配符路由捕获所有 /studio 下的请求
        @app.get("/studio/{full_path:path}", include_in_schema=False)
        async def serve_studio_app(full_path: str):
            # 允许直接访问 public 下的非 assets 资源
            file_path = _FRONTEND_DIST / full_path
            if full_path and file_path.is_file():
                return FileResponse(str(file_path))
            # 其它任何子路径，统统返回 index.html 交给 React Router 接管
            return FileResponse(str(_FRONTEND_DIST / "index.html"), media_type="text/html")
        
        # 兼容不带 trailing slash 的访问
        @app.get("/studio", include_in_schema=False)
        async def serve_studio_index():
            return FileResponse(str(_FRONTEND_DIST / "index.html"), media_type="text/html")
        
        logger.info("Studio frontend mounted at /studio (with SPA support)")
    else:
        logger.warning(
            "Studio frontend dist not found at %s. "
            "Run 'npm run build' in studio/frontend/ to generate it.",
            _FRONTEND_DIST,
        )


def setup_studio_from_env(app: FastAPI, registry: AgentRegistry | None = None) -> bool:
    """Conditionally mount Studio based on ENABLE_STUDIO env var.

    Designed to be called at module level (outside lifespan) so routes are
    registered before the ASGI server starts accepting requests.
    Returns True if Studio was mounted.
    """
    if os.getenv("ENABLE_STUDIO", "").lower() != "true":
        return False
    try:
        setup_studio(app, registry=registry)
    except ImportError:
        logger.warning("ENABLE_STUDIO=true but studio module not found, skipping")
    except Exception:
        logger.exception("ENABLE_STUDIO=true but studio failed to load")
    return True
