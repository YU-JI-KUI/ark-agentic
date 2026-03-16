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

# 抑制第三方库的 DEBUG 日志（即使 LOG_LEVEL=DEBUG）
for _lib in ("httpcore", "httpx", "urllib3", "asyncio"):
    logging.getLogger(_lib).setLevel(logging.WARNING)

if _log_level == logging.DEBUG:
    from langchain_core.globals import set_debug
    set_debug(True)

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from ark_agentic.core.registry import AgentRegistry
from ark_agentic.api import deps as api_deps
from ark_agentic.api import chat as chat_api
from ark_agentic.agents.insurance import create_insurance_agent
from ark_agentic.agents.securities import create_securities_agent
from ark_agentic.agents.securities.tools.service_client import get_mock_mode

logger = logging.getLogger(__name__)

_registry = AgentRegistry()


def _env_flag(name: str) -> bool:
    return os.getenv(name, "").lower() in ("true", "1")


@asynccontextmanager
async def lifespan(app: FastAPI):
    _registry.register("insurance", create_insurance_agent(
        enable_memory=_env_flag("ENABLE_MEMORY"),
        enable_thinking_tags=_env_flag("ENABLE_THINKING_TAGS"),
    ))
    _registry.register("securities", create_securities_agent(
        enable_memory=_env_flag("ENABLE_MEMORY"),
    ))

    if os.getenv("ENABLE_STUDIO", "").lower() == "true":
        try:
            from ark_agentic.agents.meta_builder import create_meta_builder_from_env
            _registry.register("meta_builder", create_meta_builder_from_env())
            logger.info("MetaBuilder Agent registered")
        except Exception as e:
            logger.warning("MetaBuilder Agent failed to initialize, skipping: %s", e)

    api_deps.init_registry(_registry)

    for agent_id in _registry.list_ids():
        runner = _registry.get(agent_id)
        runner.warmup()
        logger.info("Agent '%s' warmed up", agent_id)

    logger.info("Unified API started with agents: %s", _registry.list_ids())
    yield
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

# ---- 静态文件 & 测试 UI ----
_STATIC_DIR = Path(__file__).parent / "static"
if _STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


@app.get("/", include_in_schema=False)
async def root():
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/insurance")


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


# ---- 条件挂载 Studio ----
if os.getenv("ENABLE_STUDIO", "").lower() == "true":
    try:
        from ark_agentic.studio import setup_studio
        setup_studio(app)
        logger.info("Studio mounted at /studio")
    except ImportError:
        logger.warning("ENABLE_STUDIO=true but studio module not found, skipping")
    except Exception as e:
        logger.exception("ENABLE_STUDIO=true but studio failed to load: %s", e)


def main() -> None:
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
