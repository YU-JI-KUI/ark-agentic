"""
Chat API 路由
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, AsyncIterator

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse

from ark_agentic.core.stream.event_bus import StreamEventBus
from ark_agentic.core.stream.events import AgentStreamEvent
from ark_agentic.core.stream.output_formatter import create_formatter

from .deps import get_agent
from .models import ChatRequest, ChatResponse

logger = logging.getLogger(__name__)

router = APIRouter()



@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    x_ark_session_id: str | None = Header(None, alias="x-ark-session-id"),
    x_ark_user_id: str | None = Header(None, alias="x-ark-user-id"),
    x_ark_message_id: str | None = Header(None, alias="x-ark-message-id"),
    x_ark_trace_id: str | None = Header(None, alias="x-ark-trace-id"),
):
    """Chat 端点，支持流式和非流式响应。

    """
    agent = get_agent(request.agent_id)

    # ── resolve user_id (mandatory) ──
    user_id = request.user_id or x_ark_user_id
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required (body or x-ark-user-id header)")

    # ── resolve message_id (optional, auto-generate) ──
    message_id = request.message_id or x_ark_message_id or str(uuid.uuid4())

    # ── build input_context ──
    input_context: dict[str, Any] = {}
    if request.context:
        for k, v in request.context.items():
            input_context[f"user:{k}" if ":" not in k else k] = v
    input_context["user:id"] = user_id
    if x_ark_trace_id:
        input_context["temp:trace_id"] = x_ark_trace_id
    if request.idempotency_key:
        input_context["temp:idempotency_key"] = request.idempotency_key
    input_context["temp:message_id"] = message_id

    # ── display-only metadata for Studio session-detail UI ──
    _chat_req: dict[str, Any] = {"message_id": message_id}
    if request.run_options is not None:
        if request.run_options.model:
            _chat_req["model"] = request.run_options.model
        provider = getattr(request.run_options, "provider", None)
        if provider:
            _chat_req["provider"] = provider
    if request.source_bu_type:
        _chat_req["source_bu_type"] = request.source_bu_type
    if request.app_type:
        _chat_req["app_type"] = request.app_type
    if request.use_history is False:
        _chat_req["use_history"] = False
    if request.history:
        _chat_req["external_history_count"] = len(request.history)
    input_context["meta:chat_request"] = _chat_req

    # ── resolve session_id ──
    session_id = request.session_id or x_ark_session_id
    if not session_id:
        session_state = {"user:id": user_id}
        session = await agent.session_manager.create_session(user_id=user_id, state=session_state)
        session_id = session.session_id
        logger.info(f"Created new session: {session_id}")
    else:
        session = agent.session_manager.get_session(session_id)
        if not session:
            session = await agent.session_manager.load_session(session_id, user_id)
        if not session:
            logger.warning(
                f"Session {session_id} not found in agent {request.agent_id}, "
                "creating new session (possible agent switch)"
            )
            session_state = {"user:id": user_id}
            session = await agent.session_manager.create_session(user_id=user_id, state=session_state)
            session_id = session.session_id
            logger.info(f"Created new session after agent switch: {session_id}")

    run_options = request.run_options
    # ── external history ──
    raw_history = (
        [m.model_dump() for m in request.history] if request.history else None
    )

    run_id = str(uuid.uuid4())
    if not request.stream:
        result = await agent.run(
            session_id=session_id,
            user_input=request.message,
            user_id=user_id,
            input_context=input_context,
            stream=False,
            run_options=run_options,
            history=raw_history,
            use_history=request.use_history,
        )
        tool_calls = []
        if result.tool_calls:
            for tc in result.tool_calls:
                tool_calls.append({"name": tc.name, "arguments": tc.arguments})
        return ChatResponse(
            session_id=session_id,
            message_id=message_id,
            response=result.response.content or "",
            tool_calls=tool_calls,
            turns=result.turns,
        )

    # ---- 流式响应 ----
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
            result = await agent.run(
                session_id=session_id,
                user_input=request.message,
                user_id=user_id,
                input_context=input_context,
                stream=True,
                run_options=run_options,
                handler=bus,
                history=raw_history,
                use_history=request.use_history,
            )
            tool_calls = []
            if result.tool_calls:
                for tc in result.tool_calls:
                    tool_calls.append({"name": tc.name, "arguments": tc.arguments})

            bus.emit_completed(
                message=result.response.content or "",
                tool_calls=tool_calls if tool_calls else None,
                turns=result.turns,
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
                    sse_line = formatter.format(event)
                    if sse_line is not None:
                        yield sse_line
                except asyncio.TimeoutError:
                    continue
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(event_stream(), media_type="text/event-stream")
