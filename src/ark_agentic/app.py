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

from contextlib import AsyncExitStack

from ark_agentic.core.registry import AgentRegistry
from ark_agentic.core.plugin import Plugin
from ark_agentic.api.context import AppContext
from ark_agentic.bootstrap import bootstrap_storage
from ark_agentic.api import deps as api_deps
from ark_agentic.api import chat as chat_api
from ark_agentic.agents import register_all as register_all_agents
from ark_agentic.core.observability import setup_tracing_from_env, shutdown_tracing
from ark_agentic.plugins.jobs.plugin import JobsPlugin
from ark_agentic.plugins.notifications.plugin import NotificationsPlugin
from ark_agentic.plugins.studio.plugin import StudioPlugin
from ark_agentic.agents.securities.tools.service.mock_mode import get_mock_mode

logger = logging.getLogger(__name__)

_registry = AgentRegistry()

# Built-in plugins. Order matters: NotificationsPlugin populates
# ``app_ctx.notifications`` before JobsPlugin reads it.
PLUGINS: list[Plugin] = [
    NotificationsPlugin(),
    JobsPlugin(),
    StudioPlugin(),
]


def _env_flag(name: str) -> bool:
    return os.getenv(name, "").lower() in ("true", "1")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Step 0: schema bootstrap ──
    await bootstrap_storage()
    logger.info("Storage bootstrapped (DB_TYPE=%s)", os.getenv("DB_TYPE", "file"))

    # Plugin-owned schema. ``bootstrap_storage`` already covers domains
    # known to it; plugins added later (or written by users via CLI)
    # can opt in via their own ``init_schema``.
    for p in PLUGINS:
        if p.is_enabled():
            await p.init_schema()

    tracer_provider = setup_tracing_from_env(service_name="ark-agentic-api")

    # ── Step 1: 注册 Agents（独立于 plugin 加载）────────────────────────
    register_all_agents(
        _registry,
        enable_memory=_env_flag("ENABLE_MEMORY"),
        enable_dream=_env_flag("ENABLE_DREAM") if os.getenv("ENABLE_DREAM") else True,
    )
    api_deps.init_registry(_registry)

    # ── Step 2: enter every enabled plugin's lifespan ──────────────────
    async with AsyncExitStack() as stack:
        ctx = AppContext(registry=_registry)
        for p in PLUGINS:
            if not p.is_enabled():
                continue
            value = await stack.enter_async_context(p.lifespan(ctx))
            setattr(ctx, p.name, value)
            logger.info("Plugin %r started", p.name)

        app.state.ctx = ctx

        # ── Step 3: warmup agents ──
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

# Windows Update / CryptSvc 会把证书吊销列表请求（disallowedcertstl.cab 等）
# 路由到本机监听端口，产生无意义的 404 日志。直接静默返回 204。
@app.middleware("http")
async def _drop_windows_update_probes(request, call_next):
    if "/msdownload/update/" in request.url.path:
        from fastapi.responses import Response
        return Response(status_code=204)
    return await call_next(request)

# ---- 挂载路由 ----
# Always-on: chat. Plugin routes mount here too, gated by is_enabled().
app.include_router(chat_api.router)
for _plugin in PLUGINS:
    if _plugin.is_enabled():
        _plugin.install_routes(app)
        logger.info("Plugin %r routes mounted", _plugin.name)

# ---- 静态文件 & 测试 UI ----
_STATIC_DIR = Path(__file__).parent / "static"
if _STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

_README_PATH = Path(__file__).resolve().parents[2] / "README.md"
_WIKI_ROOT = Path(__file__).resolve().parents[2] / "repowiki"


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


@app.get("/api/wiki/tree", include_in_schema=False)
async def get_wiki_tree():
    """返回 repowiki 两种语言的目录树，按 repowiki-metadata.json 的 wiki_items 顺序排列。"""
    import json as _json
    from fastapi.responses import JSONResponse

    def load_order_map(lang: str) -> dict:
        """返回 {name: order_index}，顺序来自 wiki_items 列表索引。"""
        meta_path = _WIKI_ROOT / lang / "meta" / "repowiki-metadata.json"
        if not meta_path.is_file():
            return {}
        with open(meta_path, encoding="utf-8") as f:
            meta = _json.load(f)
        catalog_by_id = {c["id"]: c for c in meta.get("wiki_catalogs", [])}
        order_map: dict = {}
        for idx, item in enumerate(meta.get("wiki_items", [])):
            catalog = catalog_by_id.get(item.get("catalog_id", ""))
            if catalog:
                name = catalog.get("name", "")
                if name and name not in order_map:
                    order_map[name] = idx
        return order_map

    def build_tree(base: Path, rel: Path, order_map: dict) -> list:
        target = base / rel
        if not target.is_dir():
            return []

        def sort_key(p: Path) -> tuple:
            display = p.stem if p.suffix == ".md" else p.name
            return (order_map.get(display, 9999), p.name.lower())

        items = []
        for entry in sorted(target.iterdir(), key=sort_key):
            entry_rel = rel / entry.name
            if entry.is_dir():
                children = build_tree(base, entry_rel, order_map)
                if children:
                    items.append({"type": "dir", "name": entry.name, "path": str(entry_rel).replace("\\", "/"), "children": children})
            elif entry.suffix == ".md":
                items.append({"type": "file", "name": entry.stem, "path": str(entry_rel).replace("\\", "/")})
        return items

    result = {}
    for lang in ("zh", "en"):
        content_dir = _WIKI_ROOT / lang / "content"
        order_map = load_order_map(lang)
        result[lang] = build_tree(content_dir, Path("."), order_map) if content_dir.is_dir() else []
    return JSONResponse(result)


@app.get("/api/wiki/{lang}/{path:path}", include_in_schema=False)
async def get_wiki_page(lang: str, path: str):
    """返回指定 wiki 页面的 Markdown 内容。"""
    from fastapi.responses import PlainTextResponse, Response
    if lang not in ("zh", "en"):
        return Response(status_code=400, content="invalid lang")
    file_path = _WIKI_ROOT / lang / "content" / path
    if not file_path.is_file() or file_path.suffix != ".md":
        return Response(status_code=404, content="not found")
    # 安全检查：防止路径穿越
    try:
        file_path.resolve().relative_to((_WIKI_ROOT / lang / "content").resolve())
    except ValueError:
        return Response(status_code=403, content="forbidden")
    return PlainTextResponse(file_path.read_text(encoding="utf-8"), media_type="text/markdown; charset=utf-8")


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
