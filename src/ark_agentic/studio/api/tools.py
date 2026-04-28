"""
Studio Tools API — 薄 HTTP 层

参数校验 + 调用 tool_service，不含业务逻辑。
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ark_agentic.core.utils.env import get_agents_root
from ark_agentic.studio.services.authz_service import StudioPrincipal, require_studio_roles, require_studio_user
from ..services import tool_service
from ..services.tool_service import ToolMeta

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(require_studio_user)])


# ── Request Models ──────────────────────────────────────────────────

class ToolScaffoldRequest(BaseModel):
    name: str = Field(..., min_length=1, description="工具名 (Python 标识符)")
    description: str = Field("", description="工具描述")
    parameters: list[dict[str, Any]] = Field(
        default_factory=list,
        description="参数列表 [{name, description, type, required}]",
    )


class ToolListResponse(BaseModel):
    tools: list[ToolMeta]


# ── Endpoints ───────────────────────────────────────────────────────

@router.get("/agents/{agent_id}/tools", response_model=ToolListResponse)
async def list_tools(agent_id: str):
    """列出 Agent 的所有 Tools (AST 解析)。"""
    root = get_agents_root(__file__)
    try:
        tools = tool_service.list_tools(root, agent_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")
    return ToolListResponse(tools=tools)


@router.post("/agents/{agent_id}/tools", response_model=ToolMeta)
async def scaffold_tool(
    agent_id: str,
    req: ToolScaffoldRequest,
    _: StudioPrincipal = Depends(require_studio_roles("admin", "editor")),
):
    """生成 AgentTool Python 脚手架。"""
    root = get_agents_root(__file__)
    try:
        return tool_service.scaffold_tool(
            root, agent_id, req.name, req.description, req.parameters,
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")
    except FileExistsError:
        raise HTTPException(status_code=409, detail=f"Tool already exists: {req.name}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
