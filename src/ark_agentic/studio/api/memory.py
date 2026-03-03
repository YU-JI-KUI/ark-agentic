"""
Studio Memory API — 占位模块

MVP 阶段 Memory 功能不实施，返回 501 Not Implemented。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.get("/agents/{agent_id}/memory")
async def get_agent_memory(agent_id: str):
    """占位：Memory 功能在 MVP 阶段不实施。"""
    raise HTTPException(
        status_code=501,
        detail="Memory management is not yet implemented. Coming soon.",
    )
