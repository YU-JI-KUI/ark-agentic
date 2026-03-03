"""
Studio Sessions API

Session 仅支持查看与编辑，不支持新建与删除。
列表与详情以磁盘 JSONL 为准；raw 读/写直接操作文件。
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from ark_agentic.api.deps import get_registry
from ark_agentic.core.persistence import RawJsonlValidationError, serialize_tool_result

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Models ──────────────────────────────────────────────────────────

class SessionItem(BaseModel):
    session_id: str
    message_count: int
    state: dict[str, Any] = Field(default_factory=dict)


class SessionListResponse(BaseModel):
    sessions: list[SessionItem]


class MessageItem(BaseModel):
    role: str
    content: str | None
    tool_calls: list[dict[str, Any]] | None = None
    tool_results: list[dict[str, Any]] | None = None
    thinking: str | None = None
    metadata: dict[str, Any] | None = None


class SessionDetailResponse(BaseModel):
    session_id: str
    message_count: int
    state: dict[str, Any] = Field(default_factory=dict)
    messages: list[MessageItem]


def _message_to_item(msg: Any) -> MessageItem:
    """序列化 AgentMessage 为 MessageItem（含 tool_results、thinking、metadata）。"""
    role = msg.role.value if hasattr(msg.role, "value") else str(msg.role)
    content = msg.content
    tool_calls = (
        [{"name": tc.name, "arguments": tc.arguments} for tc in msg.tool_calls]
        if msg.tool_calls
        else None
    )
    tool_results = (
        [serialize_tool_result(tr) for tr in msg.tool_results]
        if msg.tool_results
        else None
    )
    thinking = getattr(msg, "thinking", None)
    metadata = getattr(msg, "metadata", None) or None
    return MessageItem(
        role=role,
        content=content,
        tool_calls=tool_calls,
        tool_results=tool_results,
        thinking=thinking,
        metadata=metadata,
    )


# ── Endpoints ───────────────────────────────────────────────────────

@router.get("/agents/{agent_id}/sessions", response_model=SessionListResponse)
async def list_agent_sessions(agent_id: str):
    """列出指定 Agent 的所有会话（以磁盘为准）。"""
    registry = get_registry()

    try:
        runner = registry.get(agent_id)
    except KeyError:
        return SessionListResponse(sessions=[])

    sessions = await runner.session_manager.list_sessions_from_disk()
    return SessionListResponse(
        sessions=[
            SessionItem(
                session_id=s.session_id,
                message_count=len(s.messages),
                state=s.state,
            )
            for s in sessions
        ]
    )


@router.get("/agents/{agent_id}/sessions/{session_id}", response_model=SessionDetailResponse)
async def get_session_detail(agent_id: str, session_id: str):
    """查看指定会话的详情和消息历史。未在内存时先从磁盘 load_session。"""
    registry = get_registry()

    try:
        runner = registry.get(agent_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")

    session = runner.session_manager.get_session(session_id)
    if session is None:
        session = await runner.session_manager.load_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    messages = [_message_to_item(msg) for msg in session.messages]
    return SessionDetailResponse(
        session_id=session.session_id,
        message_count=len(session.messages),
        state=session.state,
        messages=messages,
    )


@router.get("/agents/{agent_id}/sessions/{session_id}/raw")
async def get_session_raw(agent_id: str, session_id: str):
    """返回该会话原始 JSONL 全文（仅读磁盘）。"""
    registry = get_registry()

    try:
        runner = registry.get(agent_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")

    tm = runner.session_manager._transcript_manager
    if tm is None:
        raise HTTPException(status_code=404, detail="Persistence not enabled")
    raw = tm.read_raw(session_id)
    if raw is None:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
    return PlainTextResponse(content=raw, media_type="application/x-ndjson")


@router.put("/agents/{agent_id}/sessions/{session_id}/raw")
async def put_session_raw(agent_id: str, session_id: str, request: Request):
    """校验并全量写回会话 JSONL；写回后重载内存。"""
    registry = get_registry()

    try:
        runner = registry.get(agent_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")

    body = (await request.body()).decode("utf-8")

    tm = runner.session_manager._transcript_manager
    if tm is None:
        raise HTTPException(status_code=404, detail="Persistence not enabled")

    try:
        await tm.write_raw(session_id, body)
    except RawJsonlValidationError as e:
        detail = {"message": str(e)}
        if e.line_number is not None:
            detail["line_number"] = e.line_number
        raise HTTPException(status_code=400, detail=detail)

    await runner.session_manager.reload_session_from_disk(session_id)
    return {"status": "saved", "session_id": session_id}
