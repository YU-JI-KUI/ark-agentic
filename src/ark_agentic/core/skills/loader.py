"""
技能加载器

参考: openclaw-main/src/agents/skills/workspace.ts
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import yaml

from ..types import SkillEntry, SkillMetadata
from .base import SkillConfig

logger = logging.getLogger(__name__)

# Frontmatter 正则（匹配 YAML 前置元数据）
FRONTMATTER_PATTERN = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


class SkillLoader:
    """技能加载器

    从多个目录加载 SKILL.md 文件，支持 frontmatter 解析和优先级覆盖。
    """

    def __init__(self, config: SkillConfig | None = None) -> None:
        self.config = config or SkillConfig()
        self._skills: dict[str, SkillEntry] = {}  # id -> skill

    def load_from_directories(
        self, directories: list[str] | None = None
    ) -> dict[str, SkillEntry]:
        """从目录列表加载技能

        目录按顺序处理，后面的目录中相同 ID 的技能会覆盖前面的。

        Args:
            directories: 技能目录列表（None 则使用配置中的目录）

        Returns:
            加载的技能字典 {id: SkillEntry}
        """
        dirs = directories or self.config.skill_directories
        new_skills: dict[str, SkillEntry] = {}

        for priority, directory in enumerate(dirs):
            dir_path = Path(directory)
            if not dir_path.exists():
                logger.warning(f"Skill directory not found: {directory}")
                continue

            self._load_directory(dir_path, priority, new_skills)

        self._skills = new_skills
        logger.info(f"Loaded {len(self._skills)} skills from {len(dirs)} directories")
        return self._skills

    def _load_directory(
        self, directory: Path, priority: int, target: dict[str, SkillEntry]
    ) -> None:
        """加载单个目录下的所有技能到 target dict"""
        for item in directory.iterdir():
            if not item.is_dir():
                continue

            skill_file = item / "SKILL.md"
            if not skill_file.exists():
                continue

            try:
                skill = self._load_skill_file(skill_file, item.name, priority)
                if skill:
                    existing = target.get(skill.id)
                    if existing is None or priority < existing.source_priority:
                        target[skill.id] = skill
                        logger.debug(f"Loaded skill: {skill.id} from {skill_file}")
            except Exception as e:
                logger.error(f"Failed to load skill from {skill_file}: {e}")

    def _load_skill_file(
        self, file_path: Path, skill_id: str, priority: int
    ) -> SkillEntry | None:
        """加载单个 SKILL.md 文件"""
        content = file_path.read_text(encoding="utf-8")

        # 解析 frontmatter
        frontmatter, body = self._parse_frontmatter(content)

        # FULL 模式：自动扫描 references/ 子目录，将所有 .md 文件追加到 body
        # Dynamic 模式：references/ 由 BaseAgent._enrich_skills_with_stage_reference 按阶段注入
        references_dir = file_path.parent / "references"
        if references_dir.exists() and references_dir.is_dir():
            body = self._append_references_full(body, references_dir)

        # 构建元数据
        metadata = self._build_metadata(frontmatter, skill_id)

        # 构建全局唯一 skill id：agent_id.skill_name
        skill_id = f"{self.config.agent_id}.{skill_id}" if self.config.agent_id else skill_id

        return SkillEntry(
            id=skill_id,
            path=str(file_path.parent),
            content=body.strip(),
            metadata=metadata,
            source_priority=priority,
            enabled=frontmatter.get("enabled", True),
        )

    def _append_references_full(self, body: str, references_dir: Path) -> str:
        """FULL 模式：将 references/ 目录下所有 .md 文件内容追加到 SKILL body。

        注: Dynamic 模式下此结果会被 _enrich_skills_with_stage_reference 覆盖替换，
        但 FULL 模式下（无 _flow_stage）所有 reference 全量注入。
        """
        sections = [body]
        for ref_file in sorted(references_dir.glob("*.md")):
            ref_content = ref_file.read_text(encoding="utf-8")
            sections.append(f"\n\n---\n### Reference: {ref_file.stem}\n\n{ref_content}")
        return "".join(sections)

    def _parse_frontmatter(self, content: str) -> tuple[dict[str, Any], str]:
        """解析 YAML frontmatter

        Args:
            content: SKILL.md 文件内容

        Returns:
            (frontmatter_dict, body_content)
        """
        match = FRONTMATTER_PATTERN.match(content)
        if not match:
            return {}, content

        try:
            frontmatter = yaml.safe_load(match.group(1)) or {}
        except yaml.YAMLError as e:
            logger.warning(f"Failed to parse frontmatter: {e}")
            frontmatter = {}

        body = content[match.end():]
        return frontmatter, body

    def _build_metadata(
        self, frontmatter: dict[str, Any], skill_id: str
    ) -> SkillMetadata:
        """从 frontmatter 构建元数据。when_to_use 合并进 description，标准 skill 仅用 description。"""
        desc = (frontmatter.get("description") or "").strip()
        wtu = frontmatter.get("when_to_use")
        if wtu:
            wtu_str = wtu.strip() if isinstance(wtu, str) else str(wtu).strip()
            if wtu_str:
                desc = f"{desc}\nWhen to use: {wtu_str}" if desc else wtu_str
        return SkillMetadata(
            name=frontmatter.get("name", skill_id),
            description=desc,
            version=frontmatter.get("version", "1.0.0"),
            required_os=frontmatter.get("required_os"),
            required_binaries=frontmatter.get("required_binaries"),
            required_env_vars=frontmatter.get("required_env_vars"),
            invocation_policy=frontmatter.get(
                "invocation_policy", self.config.default_invocation_policy
            ),
            required_tools=frontmatter.get("required_tools"),
            group=frontmatter.get("group"),
            tags=frontmatter.get("tags", []),
        )

    def get_skill(self, skill_id: str) -> SkillEntry | None:
        """获取指定技能"""
        return self._skills.get(skill_id)

    def list_skills(self) -> list[SkillEntry]:
        """列出所有技能"""
        return list(self._skills.values())

    def list_skill_ids(self) -> list[str]:
        """列出所有技能 ID"""
        return list(self._skills.keys())

    def reload(self) -> dict[str, SkillEntry]:
        """重新加载所有技能"""
        return self.load_from_directories()


def load_skills_from_directory(directory: str) -> dict[str, SkillEntry]:
    """便捷函数：从单个目录加载技能"""
    loader = SkillLoader(SkillConfig(skill_directories=[directory]))
    return loader.load_from_directories()
