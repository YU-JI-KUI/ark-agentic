"""
Scaffold template strings for ark-agentic CLI.

All templates use str.format() substitution:
  - {placeholder} for substitution variables
  - {{ / }} for literal braces in output
"""

PYPROJECT_TEMPLATE = """\
[project]
name = "{project_name}"
version = "0.1.0"
description = "{project_name} - Built with ark-agentic"
requires-python = ">=3.10"
dependencies = [
    "ark-agentic[server]>=0.5.0",
    "python-dotenv>=1.0.0",
]

[project.scripts]
{project_name} = "{package_name}.app:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/{package_name}"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
"""

AGENT_MODULE_TEMPLATE = '''\
"""
{agent_display_name} 智能体

环境变量:
    SESSIONS_DIR: 会话持久化基础目录（默认 data/ark_sessions）
    MEMORY_DIR:   Memory 数据基础目录（默认 data/ark_memory）
    CONFIG_DIR:   外部插件配置基础目录（默认 data/ark_config）
"""

from __future__ import annotations

from ark_agentic import BaseAgent

from .tools import create_{agent_name_snake}_tools


class {agent_class_name}(BaseAgent):
    """{agent_display_name} 智能体。"""

    agent_id = "{agent_name_snake}"
    agent_name = "{agent_display_name}"
    agent_description = "TODO: 描述你的智能体功能"

    def build_tools(self):
        return create_{agent_name_snake}_tools()
'''

AGENT_INIT_TEMPLATE = '''\
"""
{agent_display_name} 智能体模块
"""

from .agent import {agent_class_name}

__all__ = ["{agent_class_name}"]
'''

TOOL_TEMPLATE = '''\
"""
{agent_display_name} - 工具模块

在此定义和注册业务工具。
"""

from __future__ import annotations

from ark_agentic.core.tools import AgentTool


def create_{agent_name_snake}_tools() -> list[AgentTool]:
    """返回 {agent_display_name} 智能体使用的业务工具列表。

    在此处实例化你的工具并加入返回列表。
    """
    return []
'''

ENV_SAMPLE_TEMPLATE = """\
# ---- LLM ----
LLM_PROVIDER=openai
MODEL_NAME=gpt-4o
API_KEY=

# ---- API server ----
# API_HOST=0.0.0.0
# API_PORT=8080

# ---- Data paths ----
# CONFIG_DIR=data/ark_config
# SESSIONS_DIR=data/ark_sessions
# MEMORY_DIR=data/ark_memory

# ---- Plugins (opt-in via ENABLE_*) ----
ENABLE_STUDIO=true
# ENABLE_NOTIFICATIONS=true
# ENABLE_JOB_MANAGER=true
# ENABLE_MEMORY=true

# ---- Tracing (off by default) ----
# TRACING=console
"""

API_APP_TEMPLATE = '''\
"""
{project_name} - 框架装配入口

只做装配：构造 ``Bootstrap`` 驱动选定的 plugin (MCP / API /
Notifications / Jobs / Studio) 完成 init / install_routes / start / stop。框架在
启动时自动扫描 ``agents/`` 目录下的所有 ``BaseAgent`` 子类并注册。

启用具体插件由环境变量决定（如 ``ENABLE_STUDIO=true``）；不需要的插件
保持默认即可，``Bootstrap`` 会跳过。

UI 资源（``static/index.html`` + ``static/a2ui-renderer.js``）随项目
分发，由本文件挂载到 ``/`` 与 ``/api/static``。如不需要内置 demo 页面，
删除下方的 mount 与 static 目录即可。
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

_log_level = getattr(
    logging,
    os.getenv("LOG_LEVEL", "INFO").upper(),
    logging.INFO,
)
logging.basicConfig(
    level=_log_level,
    format="%(asctime)s %(levelname)-5s %(name)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    force=True,
)

from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from ark_agentic.core.protocol.app_context import AppContext
from ark_agentic.core.protocol.bootstrap import Bootstrap
from ark_agentic.plugins.api.plugin import APIPlugin
from ark_agentic.plugins.jobs.plugin import JobsPlugin
from ark_agentic.plugins.mcp.plugin import MCPPlugin
from ark_agentic.plugins.notifications.plugin import NotificationsPlugin
from ark_agentic.plugins.studio.plugin import StudioPlugin

logger = logging.getLogger(__name__)

# Bootstrap 自动加载 AgentsLifecycle + TracingLifecycle；
# AgentsLifecycle 在 start() 时扫描 ``agents/`` 目录下的所有
# ``BaseAgent`` 子类并注册到 registry，无需手动注册。
_bootstrap = Bootstrap(
    components=[
        MCPPlugin(),
        APIPlugin(),
        NotificationsPlugin(),
        JobsPlugin(),
        StudioPlugin(),
    ],
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    ctx = AppContext()
    await _bootstrap.start(ctx)
    app.state.ctx = ctx
    try:
        yield
    finally:
        await _bootstrap.stop()


app = FastAPI(
    title="{project_name}",
    description="{project_name} - Built with ark-agentic",
    version="0.1.0",
    lifespan=lifespan,
)
_bootstrap.install_routes(app)

# ── UI: project-bundled chat-demo page ───────────────────────────────
_STATIC_DIR = Path(__file__).resolve().parent / "static"
_INDEX_HTML = _STATIC_DIR / "index.html"
if _STATIC_DIR.is_dir():
    app.mount(
        "/api/static",
        StaticFiles(directory=str(_STATIC_DIR)),
        name="api-static",
    )

    @app.get("/", include_in_schema=False)
    async def _index():
        # ENABLE_STUDIO=true 时跳到 /studio playground，否则提供项目自带的 demo
        if os.getenv("ENABLE_STUDIO", "").lower() == "true":
            return RedirectResponse(url="/studio", status_code=302)
        if _INDEX_HTML.is_file():
            return FileResponse(str(_INDEX_HTML), media_type="text/html")
        return {{"status": "ok", "message": "no UI bundled"}}


def main() -> None:
    import uvicorn

    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", "8080"))
    logger.info(f"Starting {project_name} API on {{host}}:{{port}}")
    uvicorn.run(
        "{package_name}.app:app",
        host=host,
        port=port,
        reload=False,
        log_level=os.getenv("LOG_LEVEL", "info").lower(),
    )


if __name__ == "__main__":
    main()
'''

PIP_CONF_TEMPLATE = """\
[global]
index-url = http://maven.abc.com.cn/repository/pypi/simple/
trusted-host = maven.abc.com.cn
"""

AGENT_JSON_TEMPLATE = """\
{{
  "id": "{agent_name_snake}",
  "name": "{agent_display_name}",
  "description": "TODO: 描述你的智能体功能",
  "status": "active"
}}
"""
