"""
统一 FastAPI 服务入口

提供统一 API 接口调用不同 agent，支持 SSE 流式输出。
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

# ---- 全局日志配置 ----
logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s %(levelname)-5s %(name)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    force=True,
)

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ark_agentic.core.runner import AgentRunner
from ark_agentic.core.types import RunOptions
from ark_agentic.agents.insurance.api import create_insurance_agent_from_env

logger = logging.getLogger(__name__)


class AgentRegistry:
    """Agent 注册表"""

    def __init__(self) -> None:
        self._agents: dict[str, AgentRunner] = {}

    def get(self, agent_id: str) -> AgentRunner:
        if agent_id not in self._agents:
            raise KeyError(agent_id)
        return self._agents[agent_id]

    def register(self, agent_id: str, agent: AgentRunner) -> None:
        self._agents[agent_id] = agent

    def list_ids(self) -> list[str]:
        return list(self._agents.keys())


_registry = AgentRegistry()


def _get_agent(agent_id: str) -> AgentRunner:
    try:
        return _registry.get(agent_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")


class ChatRequest(BaseModel):
    """Chat 请求模型"""
    agent_id: str = Field("insurance", description="Agent ID")
    message: str = Field(..., description="用户消息内容")
    session_id: str | None = Field(None, description="会话 ID，为空则创建新会话")
    stream: bool = Field(False, description="是否启用 SSE 流式输出")
    run_options: RunOptions | None = Field(None, description="运行选项（模型、温度等覆盖）")
    # 业务上下文字段
    user_id: str | None = Field(None, description="用户 ID")
    context: dict[str, Any] | None = Field(None, description="业务上下文数据")
    idempotency_key: str | None = Field(None, description="幂等键，防止重复请求")


class ChatResponse(BaseModel):
    """Chat 响应模型"""
    session_id: str
    response: str
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    turns: int = 0
    usage: dict[str, int] | None = Field(None, description="Token 使用统计")


class SessionCreateRequest(BaseModel):
    agent_id: str = Field("insurance", description="Agent ID")
    metadata: dict[str, Any] | None = Field(None, description="会话元数据")


class SessionResponse(BaseModel):
    session_id: str
    message_count: int
    metadata: dict[str, Any] = Field(default_factory=dict)


class MessageItem(BaseModel):
    role: str
    content: str | None
    tool_calls: list[dict[str, Any]] | None = None


class SessionHistoryResponse(BaseModel):
    session_id: str
    messages: list[MessageItem]


@asynccontextmanager
async def lifespan(app: FastAPI):
    _registry.register("insurance", create_insurance_agent_from_env())
    logger.info("Unified API started")
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

# 静态文件 & 测试 UI
_STATIC_DIR = Path(__file__).parent / "static"
if _STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


@app.get("/", include_in_schema=False)
async def root():
    """测试 UI 入口"""
    index = _STATIC_DIR / "index.html"
    if index.is_file():
        return FileResponse(str(index), media_type="text/html")
    return {"message": "Ark-Agentic API", "docs": "/docs"}


@app.get("/health")
async def health_check():
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    x_ark_session_key: str | None = Header(None, alias="x-ark-session-key"),
    x_ark_user_id: str | None = Header(None, alias="x-ark-user-id"),
    x_ark_trace_id: str | None = Header(None, alias="x-ark-trace-id"),
):
    """Chat 端点，支持流式和非流式响应"""
    agent = _get_agent(request.agent_id)

    # 构建业务上下文：合并 body 和 headers
    context = request.context.copy() if request.context else {}
    # 优先使用 body 中的 user_id，其次是 header
    user_id = request.user_id or x_ark_user_id
    if user_id:
        context["user_id"] = user_id
    if x_ark_trace_id:
        context["trace_id"] = x_ark_trace_id
    if request.idempotency_key:
        context["idempotency_key"] = request.idempotency_key

    # 解析 session_id：优先 body，其次 header
    session_id = request.session_id or x_ark_session_key
    if not session_id:
        # 创建新会话（使用异步版本以支持持久化）
        session_metadata = {"user_id": user_id} if user_id else {}
        session = await agent.session_manager.create_session(metadata=session_metadata)
        session_id = session.session_id
        logger.info(f"Created new session: {session_id}")
    else:
        # 尝试从内存获取，如果不存在则从持久化存储加载
        session = agent.session_manager.get_session(session_id)
        if not session:
            session = await agent.session_manager.load_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    # 生成本次执行 ID
    run_id = str(uuid.uuid4())

    if not request.stream:
        # 非流式响应
        run_options = request.run_options
        result = await agent.run(
            session_id=session_id,
            user_input=request.message,
            context=context,
            run_options=run_options,
        )
        tool_calls = []
        if result.tool_calls:
            for tc in result.tool_calls:
                tool_calls.append({"name": tc.name, "arguments": tc.arguments})
        return ChatResponse(
            session_id=session_id,
            response=result.response.content or "",
            tool_calls=tool_calls,
            turns=result.turns,
            usage={
                "prompt_tokens": result.prompt_tokens,
                "completion_tokens": result.completion_tokens,
            },
        )

    # ---- 流式响应：使用 StreamEventBus ----
    from ark_agentic.core.stream.event_bus import StreamEventBus
    from ark_agentic.core.stream.events import AgentStreamEvent

    queue: asyncio.Queue[AgentStreamEvent] = asyncio.Queue()
    done_event = asyncio.Event()
    bus = StreamEventBus(run_id=run_id, session_id=session_id, queue=queue)

    async def run_agent() -> None:
        bus.emit_created("收到您的消息，正在处理中…")
        try:
            result = await agent.run(
                session_id=session_id,
                user_input=request.message,
                context=context,
                stream_override=True,
                run_options=request.run_options,
                handler=bus,
            )
            tool_calls = []
            if result.tool_calls:
                for tc in result.tool_calls:
                    tool_calls.append({"name": tc.name, "arguments": tc.arguments})
            bus.emit_completed(
                message=result.response.content or "",
                tool_calls=tool_calls if tool_calls else None,
                turns=result.turns,
                usage={
                    "prompt_tokens": result.prompt_tokens,
                    "completion_tokens": result.completion_tokens,
                },
            )
        except Exception as exc:
            logger.exception(f"Agent run error: {exc}")
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
                    yield f"event: {event.type}\ndata: {event.model_dump_json(exclude_none=True)}\n\n"
                except asyncio.TimeoutError:
                    continue
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/sessions", response_model=SessionResponse)
async def create_session(request: SessionCreateRequest | None = None):
    agent_id = request.agent_id if request else "insurance"
    agent = _get_agent(agent_id)
    session = agent.session_manager.create_session_sync(
        metadata=request.metadata if request else None
    )
    return SessionResponse(
        session_id=session.session_id,
        message_count=len(session.messages),
        metadata=session.metadata,
    )


@app.get("/sessions/{session_id}", response_model=SessionHistoryResponse)
async def get_session(
    session_id: str,
    agent_id: str = Query("insurance"),
):
    agent = _get_agent(agent_id)
    session = agent.session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    messages = []
    for msg in session.messages:
        item = MessageItem(
            role=msg.role.value if hasattr(msg.role, "value") else str(msg.role),
            content=msg.content,
            tool_calls=[{"name": tc.name, "arguments": tc.arguments} for tc in msg.tool_calls] if msg.tool_calls else None,
        )
        messages.append(item)

    return SessionHistoryResponse(session_id=session_id, messages=messages)


@app.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str,
    agent_id: str = Query("insurance"),
):
    agent = _get_agent(agent_id)
    success = agent.session_manager.delete_session_sync(session_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
    return {"status": "deleted", "session_id": session_id}


@app.get("/sessions")
async def list_sessions(agent_id: str = Query("insurance")):
    agent = _get_agent(agent_id)
    sessions = agent.session_manager.list_sessions()
    return {
        "sessions": [
            {
                "session_id": s.session_id,
                "message_count": len(s.messages),
                "metadata": s.metadata,
            }
            for s in sessions
        ]
    }


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
