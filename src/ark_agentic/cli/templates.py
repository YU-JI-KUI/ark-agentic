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

MAIN_MODULE_TEMPLATE = '''\
"""
{project_name} - 基于 ark-agentic 框架的智能体应用（无 HTTP 入口）

适合 CLI / 脚本场景；HTTP + Studio 入口请用 ``{package_name}.app``。
"""

import asyncio

from dotenv import load_dotenv

from .agents.{agent_name_snake}.agent import create_{agent_name_snake}_agent

load_dotenv()


async def main():
    agent = create_{agent_name_snake}_agent()
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
{agent_display_name} 智能体

环境变量:
    SESSIONS_DIR: 会话持久化基础目录（默认 data/ark_sessions）
    MEMORY_DIR:   Memory 数据基础目录（默认 data/ark_memory）
"""

from __future__ import annotations

from pathlib import Path

from langchain_core.language_models.chat_models import BaseChatModel

from ark_agentic import AgentDef, AgentRunner, build_standard_agent
from ark_agentic.core.runtime.callbacks import RunnerCallbacks

from .tools import create_{agent_name_snake}_tools

_AGENT_DIR = Path(__file__).resolve().parent

_DEF = AgentDef(
    agent_id="{agent_name_snake}",
    agent_name="{agent_display_name}",
    agent_description="TODO: 描述你的智能体功能",
)


def create_{agent_name_snake}_agent(
    llm: BaseChatModel | None = None,
    *,
    enable_memory: bool = False,
    enable_dream: bool = True,
    callbacks: RunnerCallbacks | None = None,
) -> AgentRunner:
    """创建 {agent_display_name} 智能体。

    Args:
        llm: LLM 实例；None 时从环境变量初始化
        enable_memory: 是否启用 Memory 系统
        enable_dream: 是否启用后台记忆蒸馏（需 enable_memory=True 才有效）
        callbacks: 业务回调（鉴权、上下文注入、引用校验等）
    """
    return build_standard_agent(
        _DEF,
        skills_dir=_AGENT_DIR / "skills",
        tools=create_{agent_name_snake}_tools(),
        llm=llm,
        enable_memory=enable_memory,
        enable_dream=enable_dream,
        callbacks=callbacks,
    )
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

# ---- Plugins (opt-in via ENABLE_*) ----
# ENABLE_STUDIO=true
# ENABLE_NOTIFICATIONS=true
# ENABLE_JOB_MANAGER=true
# ENABLE_MEMORY=true

# ---- Tracing (off by default) ----
# TRACING=console
"""

API_APP_TEMPLATE = '''\
"""
{project_name} - 框架装配入口

仅做装配工作: 把项目自带的 Agent 注册到 ``AgentRegistry``，再交给
``Bootstrap`` 驱动选定的 plugin (API / Notifications / Jobs / Studio)
完成 init / install_routes / start / stop。框架自动加载强制 lifecycle
组件 (``AgentsLifecycle`` / ``TracingLifecycle``)。

启用具体插件由环境变量决定（如 ``ENABLE_STUDIO=true``）；不需要的插件
保持默认即可，``Bootstrap`` 会跳过。
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv

load_dotenv()

_log_level = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)
logging.basicConfig(
    level=_log_level,
    format="%(asctime)s %(levelname)-5s %(name)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    force=True,
)

from fastapi import FastAPI

from ark_agentic.core.protocol.app_context import AppContext
from ark_agentic.core.protocol.bootstrap import Bootstrap
from ark_agentic.plugins.api.plugin import APIPlugin
from ark_agentic.plugins.jobs.plugin import JobsPlugin
from ark_agentic.plugins.notifications.plugin import NotificationsPlugin
from ark_agentic.plugins.studio.plugin import StudioPlugin

from .agents.{agent_name_snake}.agent import create_{agent_name_snake}_agent

logger = logging.getLogger(__name__)

# Bootstrap 自动加载 AgentsLifecycle + TracingLifecycle；
# Plugin 是否启用由各自的 ENABLE_* 环境变量决定。
# 把项目自带的 agent 注册到框架 registry（``start()`` 之前完成即可）。
_bootstrap = Bootstrap(
    components=[APIPlugin(), NotificationsPlugin(), JobsPlugin(), StudioPlugin()],
)
_bootstrap.agent_registry.register(
    "{agent_name_snake}", create_{agent_name_snake}_agent(),
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
