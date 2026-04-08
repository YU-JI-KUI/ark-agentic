"""Memory 管理器 — 精简版

仅提供 workspace 路径管理和 MEMORY.md 读写。
SQLite/向量搜索/embedding 已移除；MEMORY.md 是唯一 source of truth。
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class MemoryConfig(BaseModel):
    """Memory 系统配置"""

    workspace_dir: str = ""


class MemoryManager:
    """轻量 Memory 管理器

    职责：
    - 按 user_id 定位 MEMORY.md 路径
    - 提供 read / write 便捷方法
    - 作为 runner / tools / extractor 的统一依赖入口
    """

    def __init__(self, config: MemoryConfig) -> None:
        self.config = config
        self._workspace_dir = Path(config.workspace_dir)

    def memory_path(self, user_id: str) -> Path:
        """返回用户记忆文件路径: {workspace}/{user_id}/MEMORY.md"""
        return self._workspace_dir / user_id / "MEMORY.md"

    def read_memory(self, user_id: str) -> str:
        p = self.memory_path(user_id)
        return p.read_text(encoding="utf-8") if p.exists() else ""

    def write_memory(self, user_id: str, content: str) -> tuple[list[str], list[str]]:
        """Heading-level upsert. Returns (current_headings, dropped_headings).

        Empty-body headings trigger deletion (format drops them via ``if c``).
        Returns ``([], [])`` if content contains no ``##`` headings.
        """
        from .user_profile import parse_heading_sections, format_heading_sections

        p = self.memory_path(user_id)
        p.parent.mkdir(parents=True, exist_ok=True)

        existing = p.read_text(encoding="utf-8") if p.exists() else ""
        prev_preamble, prev_sections = parse_heading_sections(existing)
        _, incoming = parse_heading_sections(content)

        if not incoming:
            return [], []

        merged = {**prev_sections, **incoming}
        p.write_text(format_heading_sections(prev_preamble, merged), encoding="utf-8")

        current = [k for k, v in merged.items() if v]
        dropped = sorted(set(prev_sections) - set(current))
        logger.info("write_memory for %s: headings=%s, dropped=%s", user_id, current, dropped)
        return current, dropped


def build_memory_manager(memory_dir: str | Path | None = None) -> MemoryManager:
    """构建 MemoryManager，兼容旧签名。"""
    if memory_dir is None:
        memory_dir = Path(tempfile.gettempdir()) / "ark_memory"
    memory_dir = Path(memory_dir)
    memory_dir.mkdir(parents=True, exist_ok=True)

    _warn_orphaned_index(memory_dir)

    return MemoryManager(MemoryConfig(workspace_dir=str(memory_dir)))


def _warn_orphaned_index(workspace: Path) -> None:
    idx_dir = workspace / ".memory"
    if idx_dir.is_dir():
        logger.warning(
            "Orphaned SQLite index directory found at %s — "
            "it is no longer used and can be safely deleted.",
            idx_dir,
        )
