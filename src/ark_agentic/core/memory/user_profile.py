"""User profile (USER.md) management.

Global user profile stored at {memory_base_dir}/_profiles/{user_id}/USER.md,
shared across all agents. Injected into system prompt on every LLM call.

Storage format: ``## section`` headings + ``- key: value`` entries.
Writes use upsert semantics — same (section, key) always occupies one line.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

_PROFILES_DIR = "_profiles"
_PROFILE_FILENAME = "USER.md"
_DEFAULT_SECTIONS: tuple[str, ...] = ("基本信息", "沟通风格", "偏好", "重要事项")

_DEFAULT_TEMPLATE = (
    "# 用户画像\n"
    + "".join(f"\n## {s}\n" for s in _DEFAULT_SECTIONS)
)

_SECTION_RE = re.compile(r"^##\s+(.+)$")


def get_profile_path(base_dir: Path, user_id: str) -> Path:
    """Return the path to a user's global profile file."""
    return base_dir / _PROFILES_DIR / user_id / _PROFILE_FILENAME


def load_user_profile(base_dir: Path, user_id: str) -> str:
    """Read USER.md content. Returns empty string if file does not exist."""
    path = get_profile_path(base_dir, user_id)
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning("Failed to read user profile %s: %s", path, e)
        return ""


def ensure_user_profile(base_dir: Path, user_id: str) -> Path:
    """Create USER.md with default template if it does not exist. Returns the path."""
    path = get_profile_path(base_dir, user_id)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_DEFAULT_TEMPLATE, encoding="utf-8")
        logger.info("Created default user profile: %s", path)
    return path


def upsert_profile_entry(
    base_dir: Path, user_id: str, section: str, key: str, value: str,
) -> None:
    """Insert or update a ``- key: value`` entry inside *section*.

    * If the section exists, the key line is replaced (or appended).
    * If the section does not exist, it is created at the end of the file.
    """
    path = ensure_user_profile(base_dir, user_id)
    content = path.read_text(encoding="utf-8")
    lines = content.split("\n")

    section_heading = f"## {section}"
    entry_line = f"- {key}: {value}"
    key_prefix = f"- {key}: "

    section_start: int | None = None
    next_section: int | None = None

    for i, line in enumerate(lines):
        if line.strip() == section_heading:
            section_start = i
        elif section_start is not None and _SECTION_RE.match(line.strip()):
            next_section = i
            break

    if section_start is None:
        # Append new section at end
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(section_heading)
        lines.append(entry_line)
    else:
        end = next_section if next_section is not None else len(lines)
        key_found = False
        for i in range(section_start + 1, end):
            if lines[i].startswith(key_prefix):
                lines[i] = entry_line
                key_found = True
                break
        if not key_found:
            # Insert after last non-empty line in section (or right after heading)
            insert_at = section_start + 1
            for i in range(end - 1, section_start, -1):
                if lines[i].strip():
                    insert_at = i + 1
                    break
            lines.insert(insert_at, entry_line)

    path.write_text("\n".join(lines), encoding="utf-8")


def write_profile(base_dir: Path, user_id: str, content: str) -> None:
    """Overwrite USER.md with *content* (for one-time migration / cleanup)."""
    path = ensure_user_profile(base_dir, user_id)
    path.write_text(content, encoding="utf-8")


def truncate_profile(content: str, max_tokens: int = 1000) -> str:
    """Truncate profile content if estimated token count exceeds max_tokens."""
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
