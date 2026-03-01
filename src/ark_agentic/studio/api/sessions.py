"""
Studio Sessions API

复用 core AgentRunner 的 session_manager 来列出 Agent 的会话。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter
from pydantic import BaseModel

from ark_agentic.api.deps import get_registry

logger = logging.getLogger(__name__)

router = APIRouter()


class SessionItem(BaseModel):
    session_id: str
    message_count: int
    state: dict = {}


class SessionListResponse(BaseModel):
    sessions: list[SessionItem]


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
