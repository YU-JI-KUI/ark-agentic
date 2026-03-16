"""用户画像管理

全局用户画像存储在 {memory_base_dir}/_profiles/{user_id}/MEMORY.md，
使用 YAML frontmatter 格式，跨 agent 共享，每次 LLM 调用注入 system prompt。

存储格式: YAML frontmatter 嵌套 section → {key: value}。
写入使用 upsert 语义——相同 (section, key) 始终覆盖。
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

_PROFILES_DIR = "_profiles"
_PROFILE_FILENAME = "MEMORY.md"
_DEFAULT_SECTIONS: tuple[str, ...] = ("基本信息", "沟通风格", "偏好", "重要事项")
_DEFAULT_FRONTMATTER: dict[str, dict[str, str]] = {s: {} for s in _DEFAULT_SECTIONS}


def get_profile_path(base_dir: Path, user_id: str) -> Path:
    """返回用户全局画像文件路径。"""
    return base_dir / _PROFILES_DIR / user_id / _PROFILE_FILENAME


def read_frontmatter(path: Path) -> dict:
    """解析 MEMORY.md 的 YAML frontmatter，返回 dict。

    文件不存在、无 frontmatter、解析失败均返回空 dict。
    """
    if not path.exists():
        return {}
    try:
        content = path.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning("Failed to read %s: %s", path, e)
        return {}

    if not content.startswith("---"):
        return {}

    end = content.find("\n---", 3)
    if end == -1:
        return {}

    yaml_text = content[4:end]
    try:
        data = yaml.safe_load(yaml_text)
        return data if isinstance(data, dict) else {}
    except yaml.YAMLError as e:
        logger.warning("Failed to parse YAML frontmatter in %s: %s", path, e)
        return {}


def write_frontmatter(path: Path, data: dict) -> None:
    """只改写 frontmatter，保留 body 不变。文件不存在则创建。"""
    path.parent.mkdir(parents=True, exist_ok=True)

    body = ""
    if path.exists():
        try:
            content = path.read_text(encoding="utf-8")
            if content.startswith("---"):
                end = content.find("\n---", 3)
                if end != -1:
                    body = content[end + 4:]
            else:
                body = "\n" + content
        except Exception:
            pass

    yaml_text = yaml.dump(
        data, allow_unicode=True, default_flow_style=False, sort_keys=False,
    )
    new_content = f"---\n{yaml_text}---{body}"
    path.write_text(new_content, encoding="utf-8")


def load_user_profile(base_dir: Path, user_id: str) -> str:
    """读取用户画像，格式化为可注入 system prompt 的文本。

    文件不存在或画像为空时返回空字符串。
    """
    data = read_frontmatter(get_profile_path(base_dir, user_id))
    if not data:
        return ""
    return _format_profile(data)


def _format_profile(data: dict) -> str:
    """将 YAML dict 格式化为可读 markdown 文本（供 system prompt 注入）。"""
    parts: list[str] = []
    for section, entries in data.items():
        if not isinstance(entries, dict) or not entries:
            continue
        parts.append(f"## {section}")
        for key, value in entries.items():
            parts.append(f"- {key}: {value}")
        parts.append("")
    return "\n".join(parts).strip()


def ensure_user_profile(base_dir: Path, user_id: str) -> Path:
    """若画像文件不存在则创建默认模板，返回路径。"""
    path = get_profile_path(base_dir, user_id)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        write_frontmatter(path, {s: {} for s in _DEFAULT_SECTIONS})
        logger.info("Created default user profile: %s", path)
    return path


def upsert_profile_entry(
    base_dir: Path, user_id: str, section: str, key: str, value: str,
) -> None:
    """在 frontmatter 的 section 中插入或更新 key: value。

    section 不存在时自动创建。
    """
    path = ensure_user_profile(base_dir, user_id)
    data = read_frontmatter(path)

    if section not in data or not isinstance(data.get(section), dict):
        data[section] = {}
    data[section][key] = value

    write_frontmatter(path, data)


def write_profile(base_dir: Path, user_id: str, content: str) -> None:
    """用 content 覆盖整个画像文件（用于一次性清理）。"""
    path = ensure_user_profile(base_dir, user_id)
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
