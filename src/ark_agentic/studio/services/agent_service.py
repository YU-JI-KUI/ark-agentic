"""
Agent Service — 业务逻辑层

提供 Agent 脚手架创建和列表扫描功能。
不依赖 FastAPI，可被 HTTP 端点和 Meta-Agent 工具共同调用。
"""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from ark_agentic.core.utils.env import resolve_agent_dir

from .skill_service import create_skill, slugify
from .tool_service import scaffold_tool, ToolParameterSpec

logger = logging.getLogger(__name__)


# ── Models ──────────────────────────────────────────────────────────

class AgentMeta(BaseModel):
    """Agent 元数据（对应 agent.json 文件）。"""
    id: str
    name: str
    description: str = ""
    status: str = "active"
    created_at: str = ""
    updated_at: str = ""


@dataclass
class AgentScaffoldSpec:
    """Agent 脚手架规格。

    Attributes:
        name: Agent 显示名称
        description: Agent 功能描述
        skills: 初始技能列表 [{name, description, content}]
        tools: 初始工具列表 [{name, description, parameters: [...]}]
        llm_config: LLM 配置 {model, temperature, ...}
    """
    name: str
    description: str = ""
    skills: list[dict[str, str]] = field(default_factory=list)
    tools: list[dict[str, Any]] = field(default_factory=list)
    llm_config: dict[str, Any] = field(default_factory=dict)


# ── Public API ──────────────────────────────────────────────────────

def scaffold_agent(
    agents_root: Path,
    spec: AgentScaffoldSpec,
) -> Path:
    """根据 spec 创建完整的 Agent 目录结构。

    Args:
        agents_root: Agent 根目录
        spec: Agent 脚手架规格

    Returns:
        创建的 Agent 目录 Path

    Raises:
        ValueError: name 为空
        FileExistsError: 同名 Agent 已存在
    """
    if not spec.name or not spec.name.strip():
        raise ValueError("Agent name must not be empty")

    slug = slugify(spec.name)
    agent_dir = agents_root / slug
    if agent_dir.exists():
        raise FileExistsError(f"Agent already exists: {slug}")

    # 创建目录结构
    agent_dir.mkdir(parents=True)
    (agent_dir / "skills").mkdir()
    (agent_dir / "tools").mkdir()

    # 写入 agent.json
    now = datetime.now(timezone.utc).isoformat()
    meta = {
        "id": slug,
        "name": spec.name,
        "description": spec.description,
        "status": "active",
        "created_at": now,
        "updated_at": now,
    }
    if spec.llm_config:
        meta["llm_config"] = spec.llm_config

    (agent_dir / "agent.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # 创建初始 Skills
    for skill_spec in spec.skills:
        try:
            create_skill(
                agents_root=agents_root,
                agent_id=slug,
                name=skill_spec.get("name", ""),
                description=skill_spec.get("description", ""),
                content=skill_spec.get("content", ""),
            )
        except Exception as e:
            logger.warning("Failed to create skill '%s': %s", skill_spec.get("name"), e)

    # 创建初始 Tools
    for tool_spec in spec.tools:
        try:
            raw_params = tool_spec.get("parameters") or []
            params = [ToolParameterSpec(**p) for p in raw_params]
            scaffold_tool(
                agents_root=agents_root,
                agent_id=slug,
                name=tool_spec.get("name", ""),
                description=tool_spec.get("description", ""),
                parameters=params,
            )
        except Exception as e:
            logger.warning("Failed to scaffold tool '%s': %s", tool_spec.get("name"), e)

    logger.info("Scaffolded agent: %s at %s", slug, agent_dir)
    return agent_dir


def list_agents(agents_root: Path) -> list[AgentMeta]:
    """扫描 agents_root 目录，返回 AgentMeta 列表。

    Skips directories starting with '_' or '.' and those without agent.json.
    """
    if not agents_root.is_dir():
        return []

    agents: list[AgentMeta] = []
    for child in sorted(agents_root.iterdir()):
        if not child.is_dir() or child.name.startswith(("_", ".")):
            continue
        meta = _read_agent_meta(child)
        if meta:
            agents.append(meta)
        else:
            agents.append(AgentMeta(id=child.name, name=child.name))
    return agents


def delete_agent(agents_root: Path, agent_id: str) -> None:
    """删除指定 Agent 的完整目录（含 skills、tools 等）。

    Raises:
        ValueError: agent_id 为 meta_builder（禁止删除 Meta-Agent 自身）
        FileNotFoundError: Agent 不存在
    """
    if agent_id == "meta_builder":
        raise ValueError("不能删除 Meta-Agent 自身。")

    agent_dir = resolve_agent_dir(agents_root, agent_id)
    if not agent_dir:
        raise FileNotFoundError(f"Agent not found: {agent_id}")

    root = agents_root.resolve()
    try:
        agent_dir.resolve().relative_to(root)
    except ValueError:
        raise ValueError(f"Path safety check failed: {agent_id}")

    shutil.rmtree(agent_dir)
    logger.info("Deleted agent: %s at %s", agent_id, agent_dir)


# ── Helpers ─────────────────────────────────────────────────────────

def _read_agent_meta(agent_dir: Path) -> AgentMeta | None:
    """从 agent 目录读取 agent.json，失败返回 None。"""
    meta_file = agent_dir / "agent.json"
    if not meta_file.is_file():
        return None
    try:
        data = json.loads(meta_file.read_text(encoding="utf-8"))
        data.setdefault("id", agent_dir.name)
        return AgentMeta(**data)
    except Exception as e:
        logger.warning("Failed to read %s: %s", meta_file, e)
        return None
