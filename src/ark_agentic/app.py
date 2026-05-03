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
from ark_agentic.core.startup_guard import validate_deployment_config
from ark_agentic.core.db.config import load_db_config_from_env
from ark_agentic.core.db.engine import get_async_engine, init_schema
from ark_agentic.api import deps as api_deps
from ark_agentic.api import chat as chat_api
from ark_agentic.api import notifications as notifications_api
from ark_agentic.agents.insurance import create_insurance_agent
from ark_agentic.agents.securities import create_securities_agent
from ark_agentic.core.observability import setup_tracing_from_env, shutdown_tracing
from ark_agentic.studio import setup_studio_from_env
from ark_agentic.studio.services.authz_service import get_studio_user_store
from ark_agentic.agents.securities.tools.service.mock_mode import get_mock_mode

logger = logging.getLogger(__name__)

_registry = AgentRegistry()


def _env_flag(name: str) -> bool:
    return os.getenv(name, "").lower() in ("true", "1")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Step 0: 部署配置检查 + DB 引擎装配 + Studio authz 预初始化 ──
    # validate_deployment_config: 多 worker + 进程内 cache 错配立刻 raise.
    # DB_TYPE=sqlite 时初始化 AsyncEngine 并建表（含 studio_users）。
    # get_studio_user_store(): 提前实例化模块级单例并跑一次 _ensure_schema,
    # 阻止首次并发请求竞态创建多份 AsyncEngine.
    validate_deployment_config()

    db_cfg = load_db_config_from_env()
    if db_cfg.db_type == "sqlite":
        engine = get_async_engine(db_cfg)
        await init_schema(engine)
        app.state.db_engine = engine
        logger.info("DB engine initialized (DB_TYPE=sqlite)")
    else:
        app.state.db_engine = None
        logger.info("DB engine skipped (DB_TYPE=file)")

    studio_store = get_studio_user_store()
    await studio_store._ensure_schema()

    # ── Step 1: 先初始化 JobManager 全局单例（如果启用）────────────────────
    # 必须在 agent warmup 之前设置，因为 warmup 时会自动向 JobManager 注册 Job
    if _env_flag("ENABLE_JOB_MANAGER"):
        try:
            from ark_agentic.services.jobs import (
                JobManager,
                UserShardScanner,
                set_job_manager,
            )
            from ark_agentic.services.notifications import (
                NotificationDelivery,
                get_notifications_base_dir,
            )
        except ImportError as e:
            raise RuntimeError(
                "ENABLE_JOB_MANAGER=1 requires 'ark-agentic[server]' extras. "
                f"Install with: pip install 'ark-agentic[server]' (cause: {e})"
            ) from e

        notification_delivery = NotificationDelivery()
        app.state.notification_delivery = notification_delivery
        # Lifespan keeps the notifications base_dir handy so the API and
        # job system can build per-agent NotificationRepository instances
        # via the storage factory.
        app.state.notifications_base_dir = get_notifications_base_dir()
        app.state.db_engine_for_notifications = app.state.db_engine

        scanner = UserShardScanner(
            max_concurrent=int(os.getenv("JOB_MAX_CONCURRENT", "50")),
            batch_size=int(os.getenv("JOB_BATCH_SIZE", "500")),
            shard_index=int(os.getenv("JOB_SHARD_INDEX", "0")),
            total_shards=int(os.getenv("JOB_TOTAL_SHARDS", "1")),
        )
        job_manager = JobManager(
            delivery=notification_delivery,
            scanner=scanner,
        )
        set_job_manager(job_manager)  # 设置全局单例
        app.state.job_manager = job_manager

    tracer_provider = setup_tracing_from_env(service_name="ark-agentic-api")

    # ── Step 2: 创建并注册 Agents ────────────────────────────────────────
    _enable_memory = _env_flag("ENABLE_MEMORY")
    _enable_dream = _env_flag("ENABLE_DREAM") if os.getenv("ENABLE_DREAM") else True
    _registry.register("insurance", create_insurance_agent(
        enable_memory=_enable_memory,
        enable_dream=_enable_dream,
    ))
    _registry.register("securities", create_securities_agent(
        enable_memory=_enable_memory,
        enable_dream=_enable_dream,
    ))

    # ── Step 2b: 组装 Proactive Jobs（临时驻留此处，待 JobRegistry 独立后迁移）──
    # Job 不属于 Agent 的职责范围，未来会提取为独立的 JobRegistry 层。
    # 当前暂存在 app.py，以保留功能同时保持 agent 文件干净。
    if _enable_memory and _env_flag("ENABLE_JOB_MANAGER"):
        from ark_agentic.core.storage.factory import (
            build_notification_repository,
        )
        from ark_agentic.services.jobs import (
            apply_proactive_job_bindings,
            build_proactive_job_bindings,
        )
        from ark_agentic.agents.insurance.proactive_job import InsuranceProactiveJob
        from ark_agentic.agents.securities.proactive_job import SecuritiesProactiveJob

        notif_base = app.state.notifications_base_dir

        def _notif_repo(agent_id: str):
            return build_notification_repository(
                base_dir=notif_base / agent_id,
                engine=app.state.db_engine,
                agent_id=agent_id,
            )

        ins_runner = _registry.get("insurance")
        if ins_runner.memory_manager is not None:
            apply_proactive_job_bindings(
                ins_runner,
                build_proactive_job_bindings(job=InsuranceProactiveJob(
                    job_id="proactive_service_insurance",
                    llm_factory=lambda: ins_runner.llm,
                    tool_registry=ins_runner.tool_registry,
                    memory_manager=ins_runner.memory_manager,
                    notification_repo=_notif_repo("insurance"),
                    cron=os.getenv("INSURANCE_PROACTIVE_CRON", "26 23 * * *"),
                )),
            )

        sec_runner = _registry.get("securities")
        if sec_runner.memory_manager is not None:
            apply_proactive_job_bindings(
                sec_runner,
                build_proactive_job_bindings(job=SecuritiesProactiveJob(
                    job_id="proactive_service_securities",
                    llm_factory=lambda: sec_runner.llm,
                    tool_registry=sec_runner.tool_registry,
                    memory_manager=sec_runner.memory_manager,
                    notification_repo=_notif_repo("securities"),
                    cron=os.getenv("SECURITIES_PROACTIVE_CRON", "0 9 * * 1-5"),
                )),
            )

    api_deps.init_registry(_registry)

    # ── Step 3: warmup 各 Agent（proactive jobs 已注册，此处触发 warmup）────
    for agent_id in _registry.list_ids():
        runner = _registry.get(agent_id)
        await runner.warmup()
        logger.info("Agent '%s' warmed up", agent_id)

    # ── Step 4: 所有 Job 注册完毕，启动调度器 ─────────────────────────────
    if hasattr(app.state, "job_manager"):
        await app.state.job_manager.start()
        logger.info("JobManager started")

    logger.info("Unified API started with agents: %s", _registry.list_ids())
    yield

    if hasattr(app.state, "job_manager"):
        await app.state.job_manager.stop()
        logger.info("JobManager stopped")

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
app.include_router(chat_api.router)
# notifications/jobs API 仅在启用 ENABLE_JOB_MANAGER 时挂载
# (依赖 services/jobs 的 apscheduler 与 services/notifications 的 fastapi 路由,
#  通过 ark-agentic[server] extras 安装)
if _env_flag("ENABLE_JOB_MANAGER"):
    app.include_router(notifications_api.router)
    logger.info("Mounted /api/notifications and /api/jobs routes")
setup_studio_from_env(app, registry=_registry)

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
