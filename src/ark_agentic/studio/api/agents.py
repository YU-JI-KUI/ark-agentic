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

def _agents_root() -> Path:
    """获取 agents/ 根目录路径。

    优先级:
      1. 环境变量 AGENTS_ROOT (显式配置, CLI 部署场景)
      2. 框架内部 src/ark_agentic/agents/ (开发场景)
    """
    if env_root := os.getenv("AGENTS_ROOT"):
        return Path(env_root).resolve()

    # 基于当前文件向上查找带 pyproject.toml 的项目根
    cursor = Path(__file__).resolve().parent
    for _ in range(8):  # 最多向上 8 层
        if (cursor / "pyproject.toml").exists():
            project_agents = cursor / "src" / "ark_agentic" / "agents"
            if project_agents.is_dir():
                return project_agents
            # CLI 生成的项目: agents/ 与 src/ 同级
            if (cursor / "agents").is_dir():
                return cursor / "agents"
            break
        cursor = cursor.parent

    # 最终回退
    return Path(__file__).resolve().parents[2] / "agents"


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
    root = _agents_root()
    agents: list[AgentMeta] = []
    if root.is_dir():
        for child in sorted(root.iterdir()):
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
    root = _agents_root()
    agent_dir = root / agent_id
    if not agent_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")
    meta = _read_agent_meta(agent_dir)
    if not meta:
        return AgentMeta(id=agent_id, name=agent_id)
    return meta


@router.post("/agents", response_model=AgentMeta, status_code=201)
async def create_agent(request: AgentCreateRequest):
    """创建新的 Agent 目录和 agent.json。"""
    root = _agents_root()
    agent_dir = root / request.id
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
