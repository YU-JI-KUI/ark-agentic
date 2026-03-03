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
import os
from pathlib import Path
from dotenv import load_dotenv

from ark_agentic import AgentRunner, RunnerConfig, create_chat_model
from ark_agentic.core.tools import ToolRegistry
from ark_agentic.core.session import SessionManager
from ark_agentic.core.prompt import PromptConfig

from .agents.default.agent import create_default_agent

load_dotenv()


async def main():
    agent = create_default_agent()
    session_id = await agent.create_session()

    print("智能体已启动，输入 'quit' 退出")
    while True:
        user_input = input("[用户] ").strip()
        if user_input.lower() in ("quit", "exit", "q"):
            break
        if not user_input:
            continue
        result = await agent.run(session_id=session_id, user_input=user_input)
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
"""

from __future__ import annotations

import os
from pathlib import Path

from langchain_core.language_models.chat_models import BaseChatModel

from ark_agentic import AgentRunner, RunnerConfig, create_chat_model
from ark_agentic.core.tools import ToolRegistry
from ark_agentic.core.session import SessionManager
from ark_agentic.core.prompt import PromptConfig
from ark_agentic.core.skills import SkillConfig, SkillLoader

_AGENT_DIR = Path(__file__).resolve().parent
_SKILLS_DIR = _AGENT_DIR / "skills"


def create_{agent_name_snake}_agent(
    llm: BaseChatModel | None = None,
    sessions_dir: str | Path | None = None,
) -> AgentRunner:
    if llm is None:
        api_key = os.getenv("DEEPSEEK_API_KEY", "")
        llm = create_chat_model(model="deepseek-chat", api_key=api_key)

    tool_registry = ToolRegistry()
    # TODO: Register your tools here
    # tool_registry.register(YourTool())

    session_manager = SessionManager(
        sessions_dir=sessions_dir,
        enable_persistence=sessions_dir is not None,
    )

    runner_config = RunnerConfig(
        max_turns=10,
        prompt_config=PromptConfig(
            agent_name="{agent_display_name}",
            agent_description="TODO: 描述你的智能体功能",
        ),
    )

    return AgentRunner(
        llm=llm,
        tool_registry=tool_registry,
        session_manager=session_manager,
        config=runner_config,
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

import asyncio
import logging
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

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

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ark_agentic import AgentRunner
from ark_agentic.core.types import RunOptions
from ark_agentic.core.stream.event_bus import StreamEventBus
from ark_agentic.core.stream.events import AgentStreamEvent
from ark_agentic.core.stream.output_formatter import create_formatter

from .agents.{agent_name_snake}.agent import create_{agent_name_snake}_agent

logger = logging.getLogger(__name__)

_runner: AgentRunner | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _runner
    _runner = create_{agent_name_snake}_agent()
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

_STATIC_DIR = Path(__file__).parent / "static"
if _STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


class ChatRequest(BaseModel):
    message: str = Field(..., description="用户消息内容")
    session_id: str | None = Field(None, description="会话 ID，为空则创建新会话")
    stream: bool = Field(False, description="是否启用 SSE 流式输出")
    run_options: RunOptions | None = Field(None)
    protocol: str = Field("internal", description="流式输出协议 (agui/internal/enterprise/alone)")
    source_bu_type: str = Field("")
    app_type: str = Field("")
    user_id: str | None = Field(None)
    context: dict[str, Any] | None = Field(None)
    idempotency_key: str | None = Field(None)


class ChatResponse(BaseModel):
    session_id: str
    response: str
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    turns: int = 0
    usage: dict[str, int] | None = Field(None)


class SSEEvent(BaseModel):
    type: str
    seq: int
    run_id: str | None = None
    session_id: str | None = None
    content: str | None = None
    delta: str | None = None
    output_index: int | None = None
    template: dict[str, Any] | None = None
    message: str | None = None
    usage: dict[str, int] | None = None
    turns: int | None = None
    tool_calls: list[dict[str, Any]] | None = None
    error_message: str | None = None



@app.get("/", include_in_schema=False)
async def root():
    index = _STATIC_DIR / "index.html"
    if index.is_file():
        return FileResponse(str(index), media_type="text/html")
    return {{"message": "{project_name} API", "docs": "/docs"}}


@app.get("/health")
async def health_check():
    return {{"status": "ok"}}


@app.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    x_ark_session_key: str | None = Header(None, alias="x-ark-session-key"),
    x_ark_user_id: str | None = Header(None, alias="x-ark-user-id"),
    x_ark_trace_id: str | None = Header(None, alias="x-ark-trace-id"),
):
    assert _runner is not None
    input_context: dict[str, Any] = {{}}
    if request.context:
        for k, v in request.context.items():
            input_context[f"user:{{k}}" if ":" not in k else k] = v
    user_id = request.user_id or x_ark_user_id
    if user_id:
        input_context["user:id"] = user_id
    if x_ark_trace_id:
        input_context["temp:trace_id"] = x_ark_trace_id
    if request.idempotency_key:
        input_context["temp:idempotency_key"] = request.idempotency_key

    session_id = request.session_id or x_ark_session_key
    if not session_id:
        session_state = {{"user:id": user_id}} if user_id else {{}}
        session = await _runner.session_manager.create_session(state=session_state)
        session_id = session.session_id
        logger.info(f"Created new session: {{session_id}}")
    else:
        session = _runner.session_manager.get_session(session_id)
        if not session:
            session = await _runner.session_manager.load_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail=f"Session not found: {{session_id}}")

    run_id = str(uuid.uuid4())
    if not request.stream:
        result = await _runner.run(
            session_id=session_id,
            user_input=request.message,
            input_context=input_context,
            run_options=request.run_options,
        )
        tool_calls = [
            {{"name": tc.name, "arguments": tc.arguments}}
            for tc in result.tool_calls
        ] if result.tool_calls else []
        return ChatResponse(
            session_id=session_id,
            response=result.response.content or "",
            tool_calls=tool_calls,
            turns=result.turns,
            usage={{
                "prompt_tokens": result.prompt_tokens,
                "completion_tokens": result.completion_tokens,
            }},
        )

    queue: asyncio.Queue[AgentStreamEvent] = asyncio.Queue()
    done_event = asyncio.Event()
    bus = StreamEventBus(run_id=run_id, session_id=session_id, queue=queue)
    formatter = create_formatter(
        request.protocol,
        source_bu_type=request.source_bu_type,
        app_type=request.app_type,
    )

    async def run_agent() -> None:
        bus.emit_created("收到您的消息，正在处理中…")
        try:
            result = await _runner.run(  # type: ignore[union-attr]
                session_id=session_id,
                user_input=request.message,
                input_context=input_context,
                stream_override=True,
                run_options=request.run_options,
                handler=bus,
            )
            tool_calls = [
                {{"name": tc.name, "arguments": tc.arguments}}
                for tc in result.tool_calls
            ] if result.tool_calls else []
            bus.emit_completed(
                message=result.response.content or "",
                tool_calls=tool_calls or None,
                turns=result.turns,
                usage={{
                    "prompt_tokens": result.prompt_tokens,
                    "completion_tokens": result.completion_tokens,
                }},
            )
        except Exception as exc:
            logger.exception(f"Agent run error: {{exc}}")
            bus.emit_failed(str(exc))
        finally:
            done_event.set()

    async def event_stream() -> AsyncIterator[str]:
        task = asyncio.create_task(run_agent())
        try:
            while True:
                if done_event.is_set() and queue.empty():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=0.1)
                    sse_line = formatter.format(event)
                    if sse_line is not None:
                        yield sse_line
                except asyncio.TimeoutError:
                    continue
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(event_stream(), media_type="text/event-stream")



def main() -> None:
    import uvicorn

    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", "8080"))
    logger.info(f"Starting {project_name} API on {{host}}:{{port}}")
    uvicorn.run(
        "{package_name}.api:app",
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

# ── Studio templates ──────────────────────────────────────────────────

STUDIO_APP_TEMPLATE = '''\
"""
{project_name} API Server (with Ark-Agentic Studio)
"""

from __future__ import annotations

import asyncio
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

from ark_agentic.core.registry import AgentRegistry
from ark_agentic.api import chat as chat_api
from ark_agentic.api import deps as api_deps

logger = logging.getLogger(__name__)

_registry = AgentRegistry()


@asynccontextmanager
async def lifespan(app: FastAPI):
    from .agents.{agent_name_snake}.agent import create_{agent_name_snake}_agent
    runner = create_{agent_name_snake}_agent()
    _registry.register("{agent_name_snake}", runner)
    api_deps.init_registry(_registry)

    if os.getenv("ENABLE_STUDIO", "false").lower() == "true":
        from ark_agentic.studio import setup_studio
        setup_studio(app)
        logger.info("Ark-Agentic Studio enabled at /studio")

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


@app.get("/health")
async def health_check():
    return {{"status": "ok"}}


def main() -> None:
    import uvicorn
    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", "8080"))
    logger.info(f"Starting {project_name} on {{host}}:{{port}}")
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

AGENT_JSON_TEMPLATE = """\
{{
  "id": "{agent_name_snake}",
  "name": "{agent_display_name}",
  "description": "TODO: 描述你的智能体功能",
  "status": "active"
}}
"""
