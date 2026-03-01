"""
Skill Service — 纯业务逻辑

提供 Skill 的 CRUD 和解析功能。
不依赖 FastAPI，可被 HTTP 端点和 Meta-Agent 工具共同调用。
"""

from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ── Models ──────────────────────────────────────────────────────────

import yaml
from pydantic import BaseModel, Field

class SkillMeta(BaseModel):
    id: str
    name: str
    description: str = ""
    file_path: str = ""
    content: str = ""
    version: str = ""
    invocation_policy: str = ""
    group: str = ""
    tags: list[str] = Field(default_factory=list)

# ... I need to replace from line 22 down to 251. Wait, that's almost the whole file!



# ── Public API ──────────────────────────────────────────────────────

def list_skills(agents_root: Path, agent_id: str) -> list[SkillMeta]:
    """扫描 skills/ 目录，解析 SKILL.md，返回 SkillMeta 列表。"""
    skills_dir = agents_root / agent_id / "skills"
    if not skills_dir.is_dir():
        raise FileNotFoundError(f"Agent not found: {agent_id}")

    skills: list[SkillMeta] = []
    for child in sorted(skills_dir.iterdir()):
        if child.is_dir() and not child.name.startswith(("_", ".")):
            meta = parse_skill_dir(child)
            if meta:
                skills.append(meta)
    return skills


def create_skill(
    agents_root: Path,
    agent_id: str,
    name: str,
    description: str = "",
    content: str = "",
) -> SkillMeta:
    """创建 Skill 目录 + SKILL.md。

    Raises:
        ValueError: name 为空或不合法
        FileNotFoundError: Agent 不存在
        FileExistsError: 同名 Skill 已存在
    """
    if not name or not name.strip():
        raise ValueError("Skill name must not be empty")

    skills_dir = agents_root / agent_id / "skills"
    if not skills_dir.is_dir():
        raise FileNotFoundError(f"Agent not found: {agent_id}")

    slug = slugify(name)
    skill_dir = skills_dir / slug

    if skill_dir.exists():
        raise FileExistsError(f"Skill already exists: {slug}")

    skill_dir.mkdir(parents=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(generate_skill_md(name, description, content), encoding="utf-8")

    logger.info("Created skill: %s/%s", agent_id, slug)
    return SkillMeta(
        id=slug,
        name=name,
        description=description,
        file_path=f"skills/{slug}/SKILL.md",
        content=skill_file.read_text(encoding="utf-8"),
    )


def update_skill(
    agents_root: Path,
    agent_id: str,
    skill_id: str,
    name: str | None = None,
    description: str | None = None,
    content: str | None = None,
) -> SkillMeta:
    """更新 SKILL.md 内容。

    Raises:
        FileNotFoundError: Skill 目录不存在
    """
    skills_dir = agents_root / agent_id / "skills"
    skill_dir = skills_dir / skill_id

    if not skill_dir.is_dir():
        raise FileNotFoundError(f"Skill not found: {skill_id}")

    # 读取现有内容，合并更新字段
    existing = parse_skill_dir(skill_dir)
    final_name = name if name is not None else (existing.name if existing else skill_id)
    final_desc = description if description is not None else (existing.description if existing else "")

    if content is not None:
        # 完整替换：如果 content 已包含 frontmatter，直接写入
        if content.startswith("---"):
            final_content = content
        else:
            final_content = generate_skill_md(final_name, final_desc, content)
    else:
        # 只更新 frontmatter 中的 name/description，保留正文
        existing_content = existing.content if existing else ""
        body = _extract_body(existing_content)
        final_content = generate_skill_md(final_name, final_desc, body)

    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(final_content, encoding="utf-8")

    logger.info("Updated skill: %s/%s", agent_id, skill_id)
    return SkillMeta(
        id=skill_id,
        name=final_name,
        description=final_desc,
        file_path=f"skills/{skill_id}/SKILL.md",
        content=final_content,
    )


def delete_skill(
    agents_root: Path,
    agent_id: str,
    skill_id: str,
) -> None:
    """删除 Skill 目录。

    Raises:
        FileNotFoundError: 目录不存在
        ValueError: 路径安全检查失败
    """
    skills_dir = agents_root / agent_id / "skills"
    skill_dir = skills_dir / skill_id

    if not skill_dir.is_dir():
        raise FileNotFoundError(f"Skill not found: {skill_id}")

    # 安全检查：确保目录确实在 skills_dir 下
    resolved = skill_dir.resolve()
    if not str(resolved).startswith(str(skills_dir.resolve())):
        raise ValueError(f"Path traversal detected: {skill_id}")

    shutil.rmtree(skill_dir)
    logger.info("Deleted skill: %s/%s", agent_id, skill_id)


# ── Helpers ─────────────────────────────────────────────────────────

def generate_skill_md(name: str, description: str, content: str) -> str:
    """生成包含 YAML frontmatter 的 SKILL.md 内容。"""
    lines = ["---"]
    lines.append(f"name: {name}")
    if description:
        if "\n" in description:
            lines.append("description: |")
            for desc_line in description.strip().split("\n"):
                lines.append(f"  {desc_line}")
        else:
            lines.append(f"description: {description}")
    lines.append("---")
    lines.append("")
    if content:
        lines.append(content)
    else:
        lines.append(f"# {name}")
        lines.append("")
        lines.append("在此编写技能的指令和规则。")
        lines.append("")
    return "\n".join(lines)


def slugify(name: str) -> str:
    """安全化目录名：过滤危险字符，空格→连字符，保留中文。"""
    # 移除危险字符
    slug = re.sub(r'[/\\.\x00]', '', name)
    # 去除首尾空格
    slug = slug.strip()
    # 空格和连续空白→连字符
    slug = re.sub(r'\s+', '-', slug)
    # 移除首尾的连字符和点
    slug = slug.strip('-.')
    if not slug:
        raise ValueError(f"Cannot create valid directory name from: {name}")
    return slug


def parse_skill_dir(skill_dir: Path) -> SkillMeta | None:
    """解析目录中的 SKILL.md，提取元数据。"""
    skill_file = skill_dir / "SKILL.md"
    if not skill_file.is_file():
        md_files = list(skill_dir.glob("*.md"))
        if not md_files:
            return None
        skill_file = md_files[0]

    try:
        content = skill_file.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning("Failed to read %s: %s", skill_file, e)
        return None

    name = skill_dir.name
    description = ""
    version = ""
    invocation_policy = ""
    group = ""
    tags = []

    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            frontmatter = parts[1]
            try:
                data = yaml.safe_load(frontmatter)
                if isinstance(data, dict):
                    name = str(data.get("name", name))
                    description = str(data.get("description", ""))
                    version = str(data.get("version", ""))
                    invocation_policy = str(data.get("invocation_policy", ""))
                    group = str(data.get("group", ""))
                    
                    tags_data = data.get("tags")
                    if isinstance(tags_data, list):
                        tags = [str(t) for t in tags_data]
                    elif isinstance(tags_data, str):
                        tags = [tags_data]
            except yaml.YAMLError as e:
                logger.warning("Failed to parse YAML frontmatter in %s: %s", skill_file, e)

    return SkillMeta(
        id=skill_dir.name,
        name=name,
        description=description,
        file_path=str(skill_file.relative_to(skill_dir.parent.parent)),
        content=content,
        version=version,
        invocation_policy=invocation_policy,
        group=group,
        tags=tags,
    )


def _extract_body(full_content: str) -> str:
    """从 SKILL.md 内容中提取 frontmatter 之后的正文部分。"""
    if not full_content.startswith("---"):
        return full_content
    parts = full_content.split("---", 2)
    if len(parts) >= 3:
        return parts[2].strip()
    return full_content
