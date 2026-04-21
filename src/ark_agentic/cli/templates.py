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
    {ark_dep}
    "python-dotenv>=1.0.0",{api_deps}
]

[project.scripts]
{project_name} = "{package_name}.main:main_sync"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/{package_name}"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
"""

MAIN_MODULE_TEMPLATE = '''\
"""
{project_name} - 基于 ark-agentic 框架的智能体应用
"""

import asyncio

from dotenv import load_dotenv

from .agents.default.agent import create_default_agent

load_dotenv()


async def main():
    agent = create_default_agent()
    user_id = "default"
    session_id = await agent.create_session(user_id=user_id)

    print("智能体已启动，输入 'quit' 退出")
    while True:
        user_input = input("[用户] ").strip()
        if user_input.lower() in ("quit", "exit", "q"):
            break
        if not user_input:
            continue
        result = await agent.run(session_id=session_id, user_input=user_input, user_id=user_id)
        print(f"[助手] {{result.response.content}}")
        print()


def main_sync():
    asyncio.run(main())


if __name__ == "__main__":
    main_sync()
'''

AGENT_MODULE_TEMPLATE = '''\
"""
{agent_name} 智能体

环境变量:
    SESSIONS_DIR: 会话持久化基础目录（默认 data/ark_sessions）
    MEMORY_DIR: Memory 数据基础目录（默认 data/ark_memory）
"""

from __future__ import annotations

from langchain_core.language_models.chat_models import BaseChatModel

from ark_agentic import AgentRunner, RunnerConfig, create_chat_model_from_env
from ark_agentic.observability import apply_observability_bindings, build_observability_bindings
from ark_agentic.core.tools import ToolRegistry
from ark_agentic.core.paths import prepare_agent_data_dir
from ark_agentic.core.session import SessionManager
from ark_agentic.core.prompt import PromptConfig


def create_{agent_name_snake}_agent(
    llm: BaseChatModel | None = None,
    *,
    enable_memory: bool = False,
) -> AgentRunner:
    if llm is None:
        llm = create_chat_model_from_env()

    tool_registry = ToolRegistry()
    # TODO: Register your tools here
    # tool_registry.register(YourTool())

    session_manager = SessionManager(
        sessions_dir=prepare_agent_data_dir("{agent_name_snake}"),
    )

    runner_config = RunnerConfig(
        max_turns=10,
        prompt_config=PromptConfig(
            agent_name="{agent_display_name}",
            agent_description="TODO: 描述你的智能体功能",
        ),
    )

    observability = build_observability_bindings(
        agent_id="default",
        agent_name=runner_config.prompt_config.agent_name,
    )

    runner = AgentRunner(
        llm=llm,
        tool_registry=tool_registry,
        session_manager=session_manager,
        config=runner_config,
        callbacks=observability.callbacks,
    )
    return apply_observability_bindings(runner, observability)
'''

AGENT_INIT_TEMPLATE = '''\
"""
{agent_display_name} 智能体模块
"""

from .agent import create_{agent_name_snake}_agent

__all__ = ["create_{agent_name_snake}_agent"]
'''

TOOL_TEMPLATE = '''\
"""
{agent_display_name} - 工具模块

在此定义和注册业务工具。
"""
'''

ENV_SAMPLE_TEMPLATE = """\
# LLM Configuration
{provider_block}

# Common options
# DEFAULT_TEMPERATURE=0.7

# Studio configuration (optional)
# ENABLE_STUDIO=true
# AGENTS_ROOT=./src/{package_name}/agents
"""

API_APP_TEMPLATE = '''\
"""
{project_name} API Server
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

_log_level = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)
logging.basicConfig(
    level=_log_level,
    format="%(asctime)s %(levelname)-5s %(name)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    force=True,
)
for _lib in ("httpcore", "httpx", "urllib3", "asyncio"):
    logging.getLogger(_lib).setLevel(logging.WARNING)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from ark_agentic.core.registry import AgentRegistry
from ark_agentic.api import chat as chat_api
from ark_agentic.api import deps as api_deps
from ark_agentic.studio import setup_studio_from_env

from .agents.{agent_name_snake}.agent import create_{agent_name_snake}_agent

logger = logging.getLogger(__name__)

_registry = AgentRegistry()


@asynccontextmanager
async def lifespan(app: FastAPI):
    runner = create_{agent_name_snake}_agent()
    _registry.register("{agent_name_snake}", runner)
    api_deps.init_registry(_registry)
    logger.info("{project_name} API started")
    yield
    logger.info("{project_name} API shutting down")


app = FastAPI(
    title="{project_name}",
    description="{project_name} Agent API",
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

app.include_router(chat_api.router)
setup_studio_from_env(app, registry=_registry)

_STATIC_DIR = Path(__file__).parent / "static"
if _STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


@app.get("/", include_in_schema=False)
async def root():
    index = _STATIC_DIR / "index.html"
    if index.is_file():
        return FileResponse(str(index), media_type="text/html")
    return {{"message": "{project_name} API", "docs": "/docs"}}


@app.get("/health")
async def health_check():
    return {{"status": "ok"}}


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
