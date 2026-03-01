"""
Studio Skills API

读取 Agent 目录下的 skills/ 中的 SKILL.md 文件。
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .agents import _agents_root

logger = logging.getLogger(__name__)

router = APIRouter()


class SkillMeta(BaseModel):
    id: str
    name: str
    description: str = ""
    file_path: str = ""
    content: str = ""


class SkillListResponse(BaseModel):
    skills: list[SkillMeta]


def _parse_skill_md(skill_dir: Path) -> SkillMeta | None:
    """解析 SKILL.md 文件，提取 name 和 description (YAML frontmatter)."""
    skill_file = skill_dir / "SKILL.md"
    if not skill_file.is_file():
        # 尝试直接读取 .md 文件
        md_files = list(skill_dir.glob("*.md"))
        if not md_files:
            return None
        skill_file = md_files[0]

    try:
        content = skill_file.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning("Failed to read %s: %s", skill_file, e)
        return None

    # 简单解析 YAML frontmatter
    name = skill_dir.name
    description = ""
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            frontmatter = parts[1]
            lines = frontmatter.strip().split("\n")
            i = 0
            while i < len(lines):
                line = lines[i]
                if line.startswith("name:"):
                    name = line[5:].strip().strip('"').strip("'")
                elif line.startswith("description:"):
                    desc = line[12:].strip()
                    if desc == "|":
                        desc_lines = []
                        i += 1
                        while i < len(lines) and (lines[i].startswith(" ") or lines[i].strip() == ""):
                            if lines[i].strip():
                                desc_lines.append(lines[i].strip())
                            i += 1
                        description = " ".join(desc_lines)
                        continue
                    else:
                        description = desc.strip('"').strip("'")
                i += 1

    return SkillMeta(
        id=skill_dir.name,
        name=name,
        description=description,
        file_path=str(skill_file.relative_to(skill_dir.parent.parent)),
        content=content,
    )


@router.get("/agents/{agent_id}/skills", response_model=SkillListResponse)
async def list_skills(agent_id: str):
    """列出 Agent 的所有 Skills。"""
    root = _agents_root()
    skills_dir = root / agent_id / "skills"
    if not skills_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")

    skills: list[SkillMeta] = []
    for child in sorted(skills_dir.iterdir()):
        if child.is_dir() and not child.name.startswith(("_", ".")):
            meta = _parse_skill_md(child)
            if meta:
                skills.append(meta)

    return SkillListResponse(skills=skills)
