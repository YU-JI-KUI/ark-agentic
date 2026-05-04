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

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

router = APIRouter(prefix="/api", tags=["notifications"])
logger = logging.getLogger(__name__)

# SSE 心跳间隔（秒）
_KEEPALIVE_INTERVAL = 30.0


# ── 请求/响应模型 ──────────────────────────────────────────────────────────

class MarkReadRequest(BaseModel):
    ids: list[str]


# ── 通知 REST 端点 ─────────────────────────────────────────────────────────

@router.get("/notifications/{agent_id}/{user_id}")
async def get_notifications(
    agent_id: str,
    user_id: str,
    request: Request,
    limit: int = 50,
    unread: bool = False,
):
    """拉取用户通知列表（按 agent 隔离）。

    用户上线时调用，获取历史（未读）通知。
    """
    store = _get_agent_store(request, agent_id)
    result = await store.list_recent(user_id, limit=limit, unread_only=unread)
    return result.model_dump()


@router.post("/notifications/{agent_id}/{user_id}/read")
async def mark_read(agent_id: str, user_id: str, body: MarkReadRequest, request: Request):
    """标记通知为已读。"""
    store = _get_agent_store(request, agent_id)
    await store.mark_read(user_id, body.ids)
    return {"ok": True, "marked": len(body.ids)}


# ── SSE 实时推送端点 ────────────────────────────────────────────────────────

@router.get("/notifications/{agent_id}/{user_id}/stream")
async def notification_stream(agent_id: str, user_id: str, request: Request):
    """SSE 实时通知流（按 agent 隔离）。

    用户在线时建立此连接，Job 产生通知时可实时推送。
    断开时自动注销，无内存泄漏。
    """
    delivery = _get_delivery(request)
    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    # SSE key 加上 agent_id，避免不同 agent 的同一个 user_id 互相覆盖
    stream_key = f"{agent_id}:{user_id}"
    delivery.register_user_online(stream_key, queue)

    # 连接建立时，先推送未读通知数量（告知前端有多少待读）
    store = _get_agent_store(request, agent_id)
    result = await store.list_recent(user_id, limit=1, unread_only=True)
    initial_event = {
        "type": "connected",
        "unread_count": result.unread_count,
    }

    async def event_gen():
        # 先发送连接确认事件
        yield f"data: {json.dumps(initial_event, ensure_ascii=False)}\n\n"

        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=_KEEPALIVE_INTERVAL)
                    yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    # 心跳，保持连接活跃
                    yield ": keepalive\n\n"
        finally:
            delivery.unregister_user(stream_key)
            logger.debug("User %s (agent=%s) disconnected from notification stream", user_id, agent_id)

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # 禁用 nginx 缓冲，保证流式实时性
        },
    )


# ── Job 管理端点 ───────────────────────────────────────────────────────────

@router.get("/jobs")
async def list_jobs(request: Request):
    """列出所有已注册的 Job 及下次执行时间。"""
    job_manager = _get_job_manager(request)
    return {"jobs": await job_manager.list_jobs()}


@router.post("/jobs/{job_id}/dispatch")
async def dispatch_job(job_id: str, request: Request):
    """手动立即触发某个 Job（供测试/管理使用）。

    注意：Job 会在后台异步执行，此接口立即返回 202。
    """
    job_manager = _get_job_manager(request)
    try:
        # 后台执行，不阻塞响应
        asyncio.create_task(job_manager.dispatch(job_id))
        return {"ok": True, "job_id": job_id, "status": "dispatched"}
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")


# ── 依赖辅助 ──────────────────────────────────────────────────────────────

def _get_agent_store(request: Request, agent_id: str):
    """Return a per-agent ``NotificationRepository`` (cached on app.state).

    The cached value is the Protocol-typed repository — file or SQLite
    depending on ``DB_TYPE``. The legacy attribute name is kept so any
    snapshot tooling that grepped ``_notif_store_*`` still finds it.
    """
    from ark_agentic.services.notifications import (
        build_notification_repository,
        get_notifications_base_dir,
    )

    cache_key = f"_notif_repo_{agent_id}"
    repo = getattr(request.app.state, cache_key, None)
    if repo is None:
        # engine=omitted: factory uses the process-wide cached engine for SQLite,
        # or skips it for file backend. No need to read app.state here.
        repo = build_notification_repository(
            base_dir=get_notifications_base_dir() / agent_id,
            agent_id=agent_id,
        )
        setattr(request.app.state, cache_key, repo)
    return repo


def _get_delivery(request: Request):
    delivery = getattr(request.app.state, "notification_delivery", None)
    if delivery is None:
        raise HTTPException(status_code=503, detail="NotificationDelivery not initialized")
    return delivery


def _get_job_manager(request: Request):
    job_manager = getattr(request.app.state, "job_manager", None)
    if job_manager is None:
        raise HTTPException(status_code=503, detail="JobManager not initialized")
    return job_manager
