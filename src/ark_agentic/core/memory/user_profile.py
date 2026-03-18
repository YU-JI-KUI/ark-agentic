"""用户画像管理

全局用户画像存储在 {memory_base_dir}/_profiles/{user_id}/MEMORY.md，
使用 heading-based markdown 格式，跨 agent 共享，每次 LLM 调用注入 system prompt。

存储格式: ## heading + content，每个 heading 代表一个属性。
写入使用 heading-level upsert 语义——同名 heading 始终覆盖。
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_PROFILES_DIR = "_profiles"
_PROFILE_FILENAME = "MEMORY.md"


def get_profile_path(base_dir: Path, user_id: str) -> Path:
    """返回用户全局画像文件路径。"""
    return base_dir / _PROFILES_DIR / user_id / _PROFILE_FILENAME


def parse_heading_sections(text: str) -> dict[str, str]:
    """解析 heading-based markdown 为 {heading: content} 有序字典。

    >>> parse_heading_sections("## 姓名\\n张三\\n\\n## 偏好\\n简洁")
    {'姓名': '张三', '偏好': '简洁'}
    """
    sections: dict[str, str] = {}
    current_heading: str | None = None
    current_lines: list[str] = []

    for line in text.split("\n"):
        if line.startswith("## "):
            if current_heading is not None:
                sections[current_heading] = "\n".join(current_lines).strip()
            current_heading = line[3:].strip()
            current_lines = []
        elif current_heading is not None:
            current_lines.append(line)

    if current_heading is not None:
        sections[current_heading] = "\n".join(current_lines).strip()

    return sections


def format_heading_sections(sections: dict[str, str]) -> str:
    """将 {heading: content} 格式化为 heading-based markdown。"""
    parts = [f"## {h}\n{c}" for h, c in sections.items() if c]
    return "\n\n".join(parts) + "\n" if parts else ""


def upsert_profile_by_heading(file_path: Path, new_content: str) -> None:
    """按 heading 合并 profile：同名 heading 替换已有，新 heading 追加。"""
    file_path.parent.mkdir(parents=True, exist_ok=True)

    existing_text = ""
    if file_path.exists():
        try:
            existing_text = file_path.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning("Failed to read profile %s: %s", file_path, e)

    existing_sections = parse_heading_sections(existing_text)
    incoming_sections = parse_heading_sections(new_content)

    if not incoming_sections:
        logger.debug("No heading sections found in incoming profile content, skipping")
        return

    merged = {**existing_sections, **incoming_sections}
    file_path.write_text(format_heading_sections(merged), encoding="utf-8")

    count = len(incoming_sections)
    logger.info("Upserted %d profile heading(s) in %s", count, file_path)


def load_user_profile(base_dir: Path, user_id: str) -> str:
    """读取用户画像，返回可直接注入 system prompt 的文本。

    文件不存在或为空时返回空字符串。
    """
    path = get_profile_path(base_dir, user_id)
    if not path.exists():
        return ""
    try:
        content = path.read_text(encoding="utf-8").strip()
        return content if content else ""
    except Exception as e:
        logger.warning("Failed to read profile %s: %s", path, e)
        return ""


def ensure_user_profile(base_dir: Path, user_id: str) -> Path:
    """若画像文件不存在则创建空文件，返回路径。"""
    path = get_profile_path(base_dir, user_id)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
        logger.info("Created empty user profile: %s", path)
    return path


def write_profile(base_dir: Path, user_id: str, content: str) -> None:
    """用 content 覆盖整个画像文件（用于 flush 全量重写）。"""
    path = get_profile_path(base_dir, user_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def truncate_profile(content: str, max_tokens: int = 1000) -> str:
    """当预估 token 数超出 max_tokens 时截断。"""
    if not content:
        return content
    from ..compaction import estimate_tokens

    tokens = estimate_tokens(content)
    if tokens <= max_tokens:
        return content
    ratio = max_tokens / tokens
    cut = int(len(content) * ratio)
    while estimate_tokens(content[:cut]) > max_tokens:
        cut = int(cut * 0.9)
    logger.warning(
        "User profile truncated: %d tokens -> %d tokens (max=%d)",
        tokens, estimate_tokens(content[:cut]), max_tokens,
    )
    return content[:cut] + "\n\n... (truncated)"
