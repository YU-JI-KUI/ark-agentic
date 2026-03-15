"""User profile (USER.md) management.

Global user profile stored at {memory_base_dir}/_profiles/{user_id}/USER.md,
shared across all agents. Injected into system prompt on every LLM call.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_PROFILES_DIR = "_profiles"
_PROFILE_FILENAME = "USER.md"

_DEFAULT_TEMPLATE = """\
# 用户画像

## 基本信息

## 沟通风格

## 偏好

## 重要事项
"""


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


def append_to_profile(base_dir: Path, user_id: str, content: str, section: str = "") -> int:
    """Append content to USER.md. Returns bytes written."""
    path = ensure_user_profile(base_dir, user_id)
    text = "\n"
    if section:
        text += f"\n{section}\n\n"
    text += content + "\n"
    with open(path, "a", encoding="utf-8") as f:
        f.write(text)
    return len(text.encode("utf-8"))


def truncate_profile(content: str, max_tokens: int = 1000) -> str:
    """Truncate profile content if estimated token count exceeds max_tokens."""
    if not content:
        return content
    from ..compaction import estimate_tokens
    tokens = estimate_tokens(content)
    if tokens <= max_tokens:
        return content
    # Binary search for the cut point
    ratio = max_tokens / tokens
    cut = int(len(content) * ratio)
    while estimate_tokens(content[:cut]) > max_tokens:
        cut = int(cut * 0.9)
    logger.warning(
        "User profile truncated: %d tokens -> %d tokens (max=%d)",
        tokens, estimate_tokens(content[:cut]), max_tokens,
    )
    return content[:cut] + "\n\n... (truncated)"
