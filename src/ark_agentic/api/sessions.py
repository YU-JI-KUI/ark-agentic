"""
Session API 路由

从 app.py 中提取的 /sessions 端点。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query

from .deps import get_agent
from .models import (
    MessageItem,
    SessionCreateRequest,
    SessionHistoryResponse,
    SessionResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()




@router.post("/sessions", response_model=SessionResponse)
async def create_session(request: SessionCreateRequest | None = None):
    agent_id = request.agent_id if request else "insurance"
    agent = get_agent(agent_id)
    session = agent.session_manager.create_session_sync(
        state=request.state if request else None
    )
    return SessionResponse(
        session_id=session.session_id,
        message_count=len(session.messages),
        state=session.state,
    )


@router.get("/sessions/{session_id}", response_model=SessionHistoryResponse)
async def get_session(
    session_id: str,
    agent_id: str = Query("insurance"),
):
    agent = get_agent(agent_id)
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


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str,
    agent_id: str = Query("insurance"),
):
    agent = get_agent(agent_id)
    success = agent.session_manager.delete_session_sync(session_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
    return {"status": "deleted", "session_id": session_id}


@router.get("/sessions")
async def list_sessions(agent_id: str = Query("insurance")):
    agent = get_agent(agent_id)
    sessions = agent.session_manager.list_sessions()
    return {
        "sessions": [
            {
                "session_id": s.session_id,
                "message_count": len(s.messages),
                "state": s.state,
            }
            for s in sessions
        ]
    }
