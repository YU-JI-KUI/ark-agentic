"""
统一 FastAPI 服务入口

瘦身后的组装器：创建 app → 挂载中间件 → 注册路由 → 条件挂载 Studio。
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
load_dotenv()

# ---- 全局日志配置 ----
_log_level = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)
logging.basicConfig(
    level=_log_level,
    format="%(asctime)s %(levelname)-5s %(name)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    force=True,
)


from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ark_agentic.core.bootstrap import Bootstrap
from ark_agentic.core.lifecycle import Lifecycle
from ark_agentic.core.registry import AgentRegistry
from ark_agentic.plugins.api.context import AppContext
from ark_agentic.plugins.api.plugin import APIPlugin
from ark_agentic.plugins.api import deps as api_deps
from ark_agentic.agents import register_all as register_all_agents
from ark_agentic.core.observability import setup_tracing_from_env, shutdown_tracing
from ark_agentic.plugins.jobs.plugin import JobsPlugin
from ark_agentic.plugins.notifications.plugin import NotificationsPlugin
from ark_agentic.plugins.playground.plugin import PlaygroundPlugin
from ark_agentic.plugins.studio.plugin import StudioPlugin

logger = logging.getLogger(__name__)

_registry = AgentRegistry()

# Built-in plugins. Order matters: APIPlugin first so other plugins can
# mount routes onto a configured FastAPI app; NotificationsPlugin must
# precede JobsPlugin since the latter reads ``ctx.notifications``.
PLUGINS: list[Lifecycle] = [
    APIPlugin(),
    PlaygroundPlugin(),
    NotificationsPlugin(),
    JobsPlugin(),
    StudioPlugin(),
]

_bootstrap = Bootstrap(PLUGINS)


def _env_flag(name: str) -> bool:
    return os.getenv(name, "").lower() in ("true", "1")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Agents + tracing are still inline here; the next commit moves them
    # into core/runtime/{agents,tracing}.py as Lifecycle components so
    # this whole function collapses to a single ``_bootstrap.lifespan``.
    register_all_agents(
        _registry,
        enable_memory=_env_flag("ENABLE_MEMORY"),
        enable_dream=_env_flag("ENABLE_DREAM") if os.getenv("ENABLE_DREAM") else True,
    )
    api_deps.init_registry(_registry)
    tracer_provider = setup_tracing_from_env(service_name="ark-agentic-api")

    ctx = AppContext(registry=_registry)
    async with _bootstrap.lifespan(app, ctx):
        for agent_id in _registry.list_ids():
            await _registry.get(agent_id).warmup()
            logger.info("Agent '%s' warmed up", agent_id)
        yield

    for agent_id in _registry.list_ids():
        await _registry.get(agent_id).close_memory()
    shutdown_tracing(tracer_provider)


app = FastAPI(
    title="Ark-Agentic API",
    description="统一 Agent API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Windows Update / CryptSvc 会把证书吊销列表请求（disallowedcertstl.cab 等）
# 路由到本机监听端口，产生无意义的 404 日志。直接静默返回 204。
@app.middleware("http")
async def _drop_windows_update_probes(request, call_next):
    if "/msdownload/update/" in request.url.path:
        from fastapi.responses import Response
        return Response(status_code=204)
    return await call_next(request)

# Plugin route mounting is delegated to Bootstrap so disabled plugins
# (and the route-mount log line) are handled in one place.
_bootstrap.install_routes(app)


def main() -> None:
    import asyncio
    import sys
    import uvicorn

    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", "8080"))

    logger.info(f"Starting Ark-Agentic API on {host}:{port}")
    uvicorn.run(
        "ark_agentic.app:app",
        host=host,
        port=port,
        reload=False,
        log_level=os.getenv("LOG_LEVEL", "info").lower(),
    )


if __name__ == "__main__":
    main()
