"""
Studio Sessions API

Session 管理能力完全内聚在 Studio 模块中。
业务 API 层只通过 /chat 返回 session_id，不暴露 Session CRUD。
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ark_agentic.api.deps import get_registry

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Models ──────────────────────────────────────────────────────────

class SessionItem(BaseModel):
    session_id: str
    message_count: int
    state: dict[str, Any] = Field(default_factory=dict)


class SessionListResponse(BaseModel):
    sessions: list[SessionItem]


class SessionCreateRequest(BaseModel):
    state: dict[str, Any] | None = Field(None, description="会话初始状态")


class MessageItem(BaseModel):
    role: str
    content: str | None
    tool_calls: list[dict[str, Any]] | None = None


class SessionDetailResponse(BaseModel):
    session_id: str
    message_count: int
    state: dict[str, Any] = Field(default_factory=dict)
    messages: list[MessageItem]


# ── Endpoints ───────────────────────────────────────────────────────

@router.get("/agents/{agent_id}/sessions", response_model=SessionListResponse)
async def list_agent_sessions(agent_id: str):
    """列出指定 Agent 的所有会话。"""
    registry = get_registry()

    try:
        runner = registry.get(agent_id)
    except KeyError:
        # Agent 可能在文件系统中存在但未注册到 runner
        return SessionListResponse(sessions=[])

    sessions = runner.session_manager.list_sessions()
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


@router.post("/agents/{agent_id}/sessions", response_model=SessionItem)
async def create_session(agent_id: str, request: SessionCreateRequest | None = None):
    """为指定 Agent 创建新会话。"""
    registry = get_registry()

    try:
        runner = registry.get(agent_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")

    session = runner.session_manager.create_session_sync(
        state=request.state if request else None
    )
    return SessionItem(
        session_id=session.session_id,
        message_count=len(session.messages),
        state=session.state,
    )


@router.get("/agents/{agent_id}/sessions/{session_id}", response_model=SessionDetailResponse)
async def get_session_detail(agent_id: str, session_id: str):
    """查看指定会话的详情和消息历史。"""
    registry = get_registry()

    try:
        runner = registry.get(agent_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")

    session = runner.session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    messages = [
        MessageItem(
            role=msg.role.value if hasattr(msg.role, "value") else str(msg.role),
            content=msg.content,
            tool_calls=[{"name": tc.name, "arguments": tc.arguments} for tc in msg.tool_calls] if msg.tool_calls else None,
        )
        for msg in session.messages
    ]

    return SessionDetailResponse(
        session_id=session.session_id,
        message_count=len(session.messages),
        state=session.state,
        messages=messages,
    )


@router.delete("/agents/{agent_id}/sessions/{session_id}")
async def delete_session(agent_id: str, session_id: str):
    """删除指定会话。"""
    registry = get_registry()

    try:
        runner = registry.get(agent_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")

    success = runner.session_manager.delete_session_sync(session_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
    return {"status": "deleted", "session_id": session_id}
