"""通知 API — REST + SSE

端点：
  GET  /api/notifications/{agent_id}/{user_id}         — 拉取历史通知（支持 unread=true 过滤）
  POST /api/notifications/{agent_id}/{user_id}/read    — 标记已读
  GET  /api/notifications/{agent_id}/{user_id}/stream  — SSE 实时推送端点
  POST /api/jobs/{job_id}/dispatch                     — 手动触发 Job（管理/测试用）
  GET  /api/jobs                                       — 列出所有已注册 Job

通知按 agent 隔离子目录：
  data/ark_notifications/{agent_id}/{user_id}/notifications.jsonl
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ark_agentic.core.protocol.context import AppContext
from .service import NotificationsService

if TYPE_CHECKING:
    from .setup import NotificationsContext

router = APIRouter(prefix="/api", tags=["notifications"])
logger = logging.getLogger(__name__)

_KEEPALIVE_INTERVAL = 30.0


# ── Typed dependencies ──────────────────────────────────────────────


def _get_ctx(request: Request) -> AppContext:
    """FastAPI dependency: resolve the AppContext attached by Bootstrap."""
    ctx = getattr(request.app.state, "ctx", None)
    if ctx is None:
        raise RuntimeError("AppContext is not initialised — did lifespan run?")
    return ctx


def get_notifications_service(
    ctx: AppContext = Depends(_get_ctx),
) -> NotificationsService:
    notifications: "NotificationsContext | None" = getattr(
        ctx, "notifications", None,
    )
    if notifications is None:
        raise HTTPException(
            status_code=503, detail="Notifications feature not enabled",
        )
    return notifications.service


def get_job_manager(ctx: AppContext = Depends(_get_ctx)):
    """Resolve JobManager from the global singleton (jobs feature owns it)."""
    from ark_agentic.plugins.jobs import get_job_manager as _get
    jm = _get()
    if jm is None:
        raise HTTPException(
            status_code=503, detail="JobManager not initialized",
        )
    return jm


# ── 请求/响应模型 ──────────────────────────────────────────────────────────

class MarkReadRequest(BaseModel):
    ids: list[str]


# ── 通知 REST 端点 ─────────────────────────────────────────────────────────

@router.get("/notifications/{agent_id}/{user_id}")
async def get_notifications(
    agent_id: str,
    user_id: str,
    limit: int = 50,
    unread: bool = False,
    service: NotificationsService = Depends(get_notifications_service),
):
    """拉取用户通知列表（按 agent 隔离）。"""
    result = await service.list_for_user(
        agent_id, user_id, limit=limit, unread_only=unread,
    )
    return result.model_dump()


@router.post("/notifications/{agent_id}/{user_id}/read")
async def mark_read(
    agent_id: str,
    user_id: str,
    body: MarkReadRequest,
    service: NotificationsService = Depends(get_notifications_service),
):
    """标记通知为已读。"""
    await service.mark_read(agent_id, user_id, body.ids)
    return {"ok": True, "marked": len(body.ids)}


# ── SSE 实时推送端点 ────────────────────────────────────────────────────────

@router.get("/notifications/{agent_id}/{user_id}/stream")
async def notification_stream(
    agent_id: str,
    user_id: str,
    request: Request,
    service: NotificationsService = Depends(get_notifications_service),
):
    """SSE 实时通知流（按 agent 隔离）。

    用户在线时建立此连接，Job 产生通知时可实时推送。
    断开时自动注销，无内存泄漏。
    """
    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    service.register_stream(agent_id, user_id, queue)

    unread = await service.unread_count(agent_id, user_id)
    initial_event = {
        "type": "connected",
        "unread_count": unread,
    }

    async def event_gen():
        yield f"data: {json.dumps(initial_event, ensure_ascii=False)}\n\n"

        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=_KEEPALIVE_INTERVAL)
                    yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            service.unregister_stream(agent_id, user_id)
            logger.debug("User %s (agent=%s) disconnected from notification stream", user_id, agent_id)

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ── Job 管理端点 ───────────────────────────────────────────────────────────

@router.get("/jobs")
async def list_jobs(jm = Depends(get_job_manager)):
    """列出所有已注册的 Job 及下次执行时间。"""
    return {"jobs": await jm.list_jobs()}


@router.post("/jobs/{job_id}/dispatch")
async def dispatch_job(job_id: str, jm = Depends(get_job_manager)):
    """手动立即触发某个 Job（供测试/管理使用）。

    注意：Job 会在后台异步执行，此接口立即返回 202。
    """
    try:
        asyncio.create_task(jm.dispatch(job_id))
        return {"ok": True, "job_id": job_id, "status": "dispatched"}
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
