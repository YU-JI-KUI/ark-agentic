"""
Studio Skills API — 薄 HTTP 层

参数校验 + 调用 skill_service，不含业务逻辑。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ark_agentic.core.utils.env import get_agents_root, resolve_agent_dir
from ..services import skill_service
from ..services.skill_service import SkillMeta

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Request Models ──────────────────────────────────────────────────

class SkillCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, description="技能名称")
    description: str = Field("", description="描述")
    content: str = Field("", description="Markdown 指令正文")


class SkillUpdateRequest(BaseModel):
    name: str | None = Field(None, description="更新名称")
    description: str | None = Field(None, description="更新描述")
    content: str | None = Field(None, description="更新 SKILL.md 正文")


class SkillListResponse(BaseModel):
    skills: list[SkillMeta]


# ── Endpoints ───────────────────────────────────────────────────────

@router.get("/agents/{agent_id}/skills", response_model=SkillListResponse)
async def list_skills(agent_id: str):
    """列出 Agent 的所有 Skills。"""
    root = get_agents_root(__file__)
    agent_dir = resolve_agent_dir(root, agent_id)
    if not agent_dir:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")
    try:
        skills = skill_service.list_skills(root, agent_id)
    except FileNotFoundError: # This should ideally not happen if agent_dir is found, but keeping for robustness
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")
    return SkillListResponse(skills=skills)


@router.post("/agents/{agent_id}/skills", response_model=SkillMeta)
async def create_skill(agent_id: str, req: SkillCreateRequest):
    """创建新 Skill。"""
    root = get_agents_root(__file__)
    try:
        return skill_service.create_skill(
            root, agent_id, req.name, req.description, req.content,
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")
    except FileExistsError:
        raise HTTPException(status_code=409, detail=f"Skill already exists")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/agents/{agent_id}/skills/{skill_id}", response_model=SkillMeta)
async def update_skill(agent_id: str, skill_id: str, req: SkillUpdateRequest):
    """更新 Skill 内容。"""
    root = get_agents_root(__file__)
    try:
        return skill_service.update_skill(
            root, agent_id, skill_id,
            name=req.name, description=req.description, content=req.content,
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Skill not found: {skill_id}")


@router.delete("/agents/{agent_id}/skills/{skill_id}")
async def delete_skill(agent_id: str, skill_id: str):
    """删除 Skill。"""
    root = get_agents_root(__file__)
    try:
        skill_service.delete_skill(root, agent_id, skill_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Skill not found: {skill_id}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "deleted", "skill_id": skill_id}
