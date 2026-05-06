"""用户记忆管理

用户记忆存储在 {workspace}/{user_id}/MEMORY.md，
使用 heading-based markdown 格式，每次 LLM 调用注入 system prompt。

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


def parse_heading_sections(text: str) -> tuple[str, dict[str, str]]:
    """解析 heading-based markdown 为 (preamble, {heading: content})。

    preamble 是第一个 ``## `` 之前的所有内容（如 ``# Title`` 行）。

    >>> parse_heading_sections("## 姓名\\n张三\\n\\n## 偏好\\n简洁")
    ('', {'姓名': '张三', '偏好': '简洁'})
    """
    preamble_lines: list[str] = []
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
        else:
            preamble_lines.append(line)

    if current_heading is not None:
        sections[current_heading] = "\n".join(current_lines).strip()

    preamble = "\n".join(preamble_lines).strip()
    return preamble, sections


def format_heading_sections(preamble: str, sections: dict[str, str]) -> str:
    """将 (preamble, {heading: content}) 格式化为 heading-based markdown。"""
    parts: list[str] = []
    if preamble:
        parts.append(preamble)
    parts.extend(f"## {h}\n{c}" for h, c in sections.items() if c)
    return "\n\n".join(parts) + "\n" if parts else ""


def upsert_profile_by_heading(file_path: Path, new_content: str) -> bool:
    """按 heading 合并：同名 heading 替换已有，新 heading 追加，保留 preamble。

    Returns True if at least one heading was written, False if content had no headings.
    """
    file_path.parent.mkdir(parents=True, exist_ok=True)

    existing_text = ""
    if file_path.exists():
        try:
            existing_text = file_path.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning("Failed to read profile %s: %s", file_path, e)

    existing_preamble, existing_sections = parse_heading_sections(existing_text)
    incoming_preamble, incoming_sections = parse_heading_sections(new_content)

    if not incoming_sections:
        logger.debug("No heading sections found in incoming content, skipping")
        return False

    preamble = existing_preamble or incoming_preamble
    merged = {**existing_sections, **incoming_sections}
    file_path.write_text(format_heading_sections(preamble, merged), encoding="utf-8")

    count = len(incoming_sections)
    logger.info("Upserted %d heading(s) in %s", count, file_path)
    return True


def truncate_profile(content: str, max_tokens: int = 2000) -> str:
    """Heading-aware truncation: 按优先级保留完整 section，不会截断半句话。"""
    if not content:
        return content
    from ..session.compaction import estimate_tokens

    tokens = estimate_tokens(content)
    if tokens <= max_tokens:
        return content

    from .rules import HEADING_PRIORITY

    preamble, sections = parse_heading_sections(content)

    ordered: list[tuple[str, str]] = []
    for h in HEADING_PRIORITY:
        if h in sections:
            ordered.append((h, sections[h]))
    for h, c in sections.items():
        if h not in HEADING_PRIORITY:
            ordered.append((h, c))

    budget = max_tokens
    if preamble:
        budget -= estimate_tokens(preamble)

    kept: dict[str, str] = {}
    for h, c in ordered:
        section_tokens = estimate_tokens(f"## {h}\n{c}")
        if budget - section_tokens < 0:
            break
        kept[h] = c
        budget -= section_tokens

    result = format_heading_sections(preamble, kept)
    kept_tokens = estimate_tokens(result)
    if kept_tokens < tokens:
        logger.warning(
            "User profile truncated: %d tokens -> %d tokens (max=%d, kept %d/%d sections)",
            tokens, kept_tokens, max_tokens, len(kept), len(sections),
        )
    return result
