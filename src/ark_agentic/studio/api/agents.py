"""
Studio Agent CRUD API

基于文件系统扫描 agents/ 目录下的 agent.json 实现 Agent 列表与详情。
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ark_agentic.core.utils.env import get_agents_root

logger = logging.getLogger(__name__)

router = APIRouter()


# ── 数据模型 ──────────────────────────────────────────────────────────

class AgentMeta(BaseModel):
    """agent.json 文件的数据模型"""
    id: str
    name: str
    description: str = ""
    status: str = "active"
    created_at: str = ""
    updated_at: str = ""


class AgentCreateRequest(BaseModel):
    """创建 Agent 的请求体"""
    id: str = Field(..., description="Agent ID (英文，用作目录名)")
    name: str = Field(..., description="Agent 显示名称")
    description: str = Field("", description="Agent 描述")


class AgentListResponse(BaseModel):
    """Agent 列表响应"""
    agents: list[AgentMeta]


# ── 辅助函数 ──────────────────────────────────────────────────────────

def _read_agent_meta(agent_dir: Path) -> AgentMeta | None:
    """从 agent 目录读取 agent.json。"""
    meta_file = agent_dir / "agent.json"
    if not meta_file.is_file():
        return None
    try:
        data = json.loads(meta_file.read_text(encoding="utf-8"))
        data.setdefault("id", agent_dir.name)
        return AgentMeta(**data)
    except (json.JSONDecodeError, Exception) as e:
        logger.warning("Failed to read %s: %s", meta_file, e)
        return None


def _write_agent_meta(agent_dir: Path, meta: AgentMeta) -> None:
    """将 AgentMeta 写入 agent.json。"""
    meta_file = agent_dir / "agent.json"
    meta_file.write_text(
        json.dumps(meta.model_dump(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


# ── 路由 ──────────────────────────────────────────────────────────────

@router.get("/agents", response_model=AgentListResponse)
async def list_agents():
    """扫描 agents/ 目录，列出所有 Agent。"""
    agents_root = get_agents_root(__file__)
    agents: list[AgentMeta] = []
    if agents_root.is_dir():
        for child in sorted(agents_root.iterdir()):
            if child.is_dir() and not child.name.startswith(("_", ".")):
                meta = _read_agent_meta(child)
                if meta:
                    agents.append(meta)
                else:
                    # 没有 agent.json 但目录存在，自动生成一个最小元数据
                    agents.append(AgentMeta(id=child.name, name=child.name))
    return AgentListResponse(agents=agents)


@router.get("/agents/{agent_id}", response_model=AgentMeta)
async def get_agent(agent_id: str):
    """获取单个 Agent 的元数据。"""
    agents_root = get_agents_root(__file__)
    agent_dir = agents_root / agent_id
    if not agent_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")
    meta = _read_agent_meta(agent_dir)
    if not meta:
        return AgentMeta(id=agent_id, name=agent_id)
    return meta


@router.post("/agents", response_model=AgentMeta, status_code=201)
async def create_agent(request: AgentCreateRequest):
    """创建新的 Agent 目录和 agent.json。"""
    agents_root = get_agents_root(__file__)
    agent_dir = agents_root / request.id
    if agent_dir.exists():
        raise HTTPException(status_code=409, detail=f"Agent already exists: {request.id}")

    # 创建目录结构
    agent_dir.mkdir(parents=True)
    (agent_dir / "skills").mkdir()
    (agent_dir / "tools").mkdir()

    now = datetime.now(timezone.utc).isoformat()
    meta = AgentMeta(
        id=request.id,
        name=request.name,
        description=request.description,
        status="active",
        created_at=now,
        updated_at=now,
    )
    _write_agent_meta(agent_dir, meta)
    logger.info("Created agent: %s at %s", request.id, agent_dir)
    return meta
