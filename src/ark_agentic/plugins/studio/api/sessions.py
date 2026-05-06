"""
Studio Sessions API

Session 仅支持查看与编辑，不支持新建与删除。
列表与详情以磁盘 JSONL 为准；raw 读/写直接操作文件。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from ark_agentic.plugins.api.deps import get_registry
from ark_agentic.core.session.format import RawJsonlValidationError, serialize_tool_result
from ark_agentic.plugins.studio.services.auth import StudioPrincipal, require_studio_roles, require_studio_user

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(require_studio_user)])


# ── Models ──────────────────────────────────────────────────────────

class SessionItem(BaseModel):
    session_id: str
    user_id: str = ""
    message_count: int
    state: dict[str, Any] = Field(default_factory=dict)
    created_at: str | None = None
    updated_at: str | None = None
    first_message: str | None = None


class SessionListResponse(BaseModel):
    sessions: list[SessionItem]


class TurnContextItem(BaseModel):
    active_skill_id: str | None = None
    tools_mounted: list[str] = Field(default_factory=list)


class MessageItem(BaseModel):
    role: str
    content: str | None
    tool_calls: list[dict[str, Any]] | None = None
    tool_results: list[dict[str, Any]] | None = None
    thinking: str | None = None
    metadata: dict[str, Any] | None = None
    finish_reason: str | None = None
    turn_context: TurnContextItem | None = None


class SessionDetailResponse(BaseModel):
    session_id: str
    message_count: int
    state: dict[str, Any] = Field(default_factory=dict)
    messages: list[MessageItem]


def _message_to_item(msg: Any) -> MessageItem:
    role = msg.role.value if hasattr(msg.role, "value") else str(msg.role)
    content = msg.content
    tool_calls = (
        [{"id": tc.id, "name": tc.name, "arguments": tc.arguments} for tc in msg.tool_calls]
        if msg.tool_calls
        else None
    )
    tool_results = (
        [serialize_tool_result(tr) for tr in msg.tool_results]
        if msg.tool_results
        else None
    )
    turn_context: TurnContextItem | None = None
    if msg.turn_context is not None:
        turn_context = TurnContextItem(
            active_skill_id=msg.turn_context.active_skill_id,
            tools_mounted=list(msg.turn_context.tools_mounted),
        )
    return MessageItem(
        role=role,
        content=content,
        tool_calls=tool_calls,
        tool_results=tool_results,
        thinking=msg.thinking,
        metadata=msg.metadata or None,
        finish_reason=msg.finish_reason,
        turn_context=turn_context,
    )


# ── Endpoints ───────────────────────────────────────────────────────

@router.get("/agents/{agent_id}/sessions", response_model=SessionListResponse)
async def list_agent_sessions(
    agent_id: str,
    user_id: str | None = Query(None, description="Filter by user_id; omit to list all users"),
):
    """列出指定 Agent 的会话（以磁盘为准）。可选按 user_id 过滤。"""
    registry = get_registry()

    try:
        runner = registry.get(agent_id)
    except KeyError:
        return SessionListResponse(sessions=[])

    summaries = await runner.session_manager.list_session_summaries(user_id=user_id)
    items: list[SessionItem] = []
    for s in summaries:
        ts_iso: str | None = None
        if s.updated_at:
            ts_iso = datetime.fromtimestamp(
                s.updated_at / 1000, tz=timezone.utc,
            ).isoformat()
        items.append(SessionItem(
            session_id=s.session_id,
            user_id=s.user_id,
            message_count=s.message_count,
            state=s.state,
            created_at=ts_iso,
            updated_at=ts_iso,
            first_message=s.first_user_message,
        ))
    return SessionListResponse(sessions=items)


@router.get("/agents/{agent_id}/sessions/{session_id}", response_model=SessionDetailResponse)
async def get_session_detail(
    agent_id: str,
    session_id: str,
    user_id: str = Query(..., description="User ID that owns this session"),
):
    """查看指定会话的详情和消息历史。"""
    registry = get_registry()

    try:
        runner = registry.get(agent_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")

    session = runner.session_manager.get_session(session_id)
    if session is None:
        session = await runner.session_manager.load_session(session_id, user_id)
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
async def get_session_raw(
    agent_id: str,
    session_id: str,
    user_id: str = Query(..., description="User ID that owns this session"),
):
    """返回该会话原始 JSONL 全文（仅读磁盘）。"""
    registry = get_registry()

    try:
        runner = registry.get(agent_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")

    raw = await runner.session_manager.get_raw_transcript(session_id, user_id)
    if raw is None:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
    return PlainTextResponse(content=raw, media_type="application/x-ndjson")


@router.put("/agents/{agent_id}/sessions/{session_id}/raw")
async def put_session_raw(
    agent_id: str,
    session_id: str,
    request: Request,
    user_id: str = Query(..., description="User ID that owns this session"),
    _: StudioPrincipal = Depends(require_studio_roles("admin", "editor")),
):
    """校验并全量写回会话 JSONL；写回后重载内存。"""
    registry = get_registry()

    try:
        runner = registry.get(agent_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")

    body = (await request.body()).decode("utf-8")

    try:
        await runner.session_manager.put_raw_transcript(
            session_id, user_id, body,
        )
    except RawJsonlValidationError as e:
        detail = {"message": str(e)}
        if e.line_number is not None:
            detail["line_number"] = e.line_number
        raise HTTPException(status_code=400, detail=detail)

    await runner.session_manager.reload_session_from_disk(session_id, user_id)
    return {"status": "saved", "session_id": session_id}
