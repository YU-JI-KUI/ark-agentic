"""Studio Users API — role grants keyed by user_id."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ark_agentic.studio.services.authz_service import (
    InvalidStudioRoleError,
    LastAdminError,
    StudioPrincipal,
    StudioRole,
    StudioUserNotFoundError,
    get_studio_user_store,
    require_studio_roles,
)

router = APIRouter()


class StudioUserItem(BaseModel):
    user_id: str
    role: StudioRole
    created_at: datetime
    updated_at: datetime
    created_by: str | None = None
    updated_by: str | None = None


class StudioUsersResponse(BaseModel):
    users: list[StudioUserItem]
    total: int
    admin_count: int
    limit: int
    offset: int


class StudioUserUpsertRequest(BaseModel):
    user_id: str = Field(..., min_length=1)
    role: StudioRole


@router.get("/users", response_model=StudioUsersResponse)
async def list_users(
    query: str = Query("", description="Filter by user_id substring"),
    role: StudioRole | None = Query(None, description="Filter by role"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _: StudioPrincipal = Depends(require_studio_roles("admin")),
):
    page = get_studio_user_store().list_users_page(
        query=query,
        role=role,
        limit=limit,
        offset=offset,
    )
    return StudioUsersResponse(
        users=[StudioUserItem(**record.__dict__) for record in page.users],
        total=page.total,
        admin_count=page.admin_count,
        limit=page.limit,
        offset=page.offset,
    )


@router.post("/users", response_model=StudioUserItem)
async def upsert_user(
    req: StudioUserUpsertRequest,
    principal: StudioPrincipal = Depends(require_studio_roles("admin")),
):
    user_id = req.user_id.strip()
    if not user_id:
        raise HTTPException(status_code=422, detail="user_id is required")
    try:
        record = get_studio_user_store().upsert_user(
            user_id,
            req.role,
            actor_user_id=principal.user_id,
        )
    except InvalidStudioRoleError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except LastAdminError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return StudioUserItem(**record.__dict__)


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: str,
    _: StudioPrincipal = Depends(require_studio_roles("admin")),
):
    try:
        get_studio_user_store().delete_user(user_id)
    except StudioUserNotFoundError:
        raise HTTPException(status_code=404, detail=f"User grant not found: {user_id}")
    except LastAdminError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"status": "deleted", "user_id": user_id}
