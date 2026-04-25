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


from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from ark_agentic.core.registry import AgentRegistry
from ark_agentic.api import deps as api_deps
from ark_agentic.api import chat as chat_api
# from ark_agentic.api import notifications as notifications_api
from ark_agentic.agents.insurance import create_insurance_agent
from ark_agentic.agents.securities import create_securities_agent
from ark_agentic.core.observability import setup_tracing_from_env, shutdown_tracing
from ark_agentic.studio import setup_studio_from_env
from ark_agentic.agents.securities.tools.service.mock_mode import get_mock_mode

logger = logging.getLogger(__name__)

_registry = AgentRegistry()


def _env_flag(name: str) -> bool:
    return os.getenv(name, "").lower() in ("true", "1")


@asynccontextmanager
async def lifespan(app: FastAPI):

    tracer_provider = setup_tracing_from_env(service_name="ark-agentic-api")

    # ── Step 2: 创建并注册 Agents ────────────────────────────────────────
    _enable_dream = _env_flag("ENABLE_DREAM") if os.getenv("ENABLE_DREAM") else True
    _registry.register("insurance", create_insurance_agent(
        enable_memory=_env_flag("ENABLE_MEMORY"),
        enable_dream=_enable_dream,
    ))
    _registry.register("securities", create_securities_agent(
        enable_memory=_env_flag("ENABLE_MEMORY"),
        enable_dream=_enable_dream,
    ))

    api_deps.init_registry(_registry)

    # ── Step 3: warmup 各 Agent（memory 已启用的会自动注册 Job）─────────────
    for agent_id in _registry.list_ids():
        runner = _registry.get(agent_id)
        await runner.warmup()
        logger.info("Agent '%s' warmed up", agent_id)

    logger.info("Unified API started with agents: %s", _registry.list_ids())
    yield

    for agent_id in _registry.list_ids():
        runner = _registry.get(agent_id)
        await runner.close_memory()
    shutdown_tracing(tracer_provider)
    logger.info("Unified API shutting down")


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


# ---- 挂载路由 ----
app.include_router(chat_api.router)
# app.include_router(notifications_api.router)
setup_studio_from_env(app, registry=_registry)

# ---- 静态文件 & 测试 UI ----
_STATIC_DIR = Path(__file__).parent / "static"
if _STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

_README_PATH = Path(__file__).resolve().parents[2] / "README.md"


@app.get("/", include_in_schema=False)
async def root():
    """项目主页。home.html 缺失时 fallback 到保险 Demo，避免 500。"""
    page = _STATIC_DIR / "home.html"
    if page.is_file():
        return FileResponse(str(page), media_type="text/html")
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/insurance")


@app.get("/api/readme", include_in_schema=False)
async def get_readme():
    """返回项目根 README.md 纯文本，供 landing 页 Docs Tab 客户端渲染。"""
    from fastapi.responses import PlainTextResponse, Response
    if _README_PATH.is_file():
        return PlainTextResponse(
            _README_PATH.read_text(encoding="utf-8"),
            media_type="text/markdown; charset=utf-8",
        )
    return Response(status_code=404, content="README.md not found")


@app.get("/insurance", include_in_schema=False)
async def insurance_page():
    page = _STATIC_DIR / "insurance.html"
    if page.is_file():
        return FileResponse(str(page), media_type="text/html")
    return {"message": "insurance page not found"}


@app.get("/securities", include_in_schema=False)
async def securities_page():
    page = _STATIC_DIR / "securities.html"
    if page.is_file():
        return FileResponse(str(page), media_type="text/html")
    return {"message": "securities page not found"}


@app.get("/health")
async def health_check():
    return {"status": "ok"}


@app.get("/api/admin/securities-mock", include_in_schema=False)
async def get_securities_mock_mode():
    """返回服务级默认 mock 状态（来自 SECURITIES_SERVICE_MOCK 环境变量，只读）"""
    return {"mock": get_mock_mode()}


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
