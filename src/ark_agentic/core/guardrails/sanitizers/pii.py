"""Simple recursive redaction for visible channels.

This is intentionally conservative: keep raw tool outputs untouched while
masking obvious sensitive values in model-visible and UI-visible channels.
"""

from __future__ import annotations

import re
from typing import Any

_BANK_CARD_RE = re.compile(r"(?<!\d)(\d{12,19})(?!\d)")
_CN_ID_RE = re.compile(r"(?<![0-9A-Za-z])([1-9]\d{16}[\dXx])(?![0-9A-Za-z])")
_OPENAI_KEY_RE = re.compile(r"\bsk-[A-Za-z0-9_\-]{12,}\b")
_BEARER_TOKEN_RE = re.compile(r"(?i)\b(bearer\s+)([A-Za-z0-9._\-]{12,})\b")


def _mask_digits(raw: str) -> str:
    if len(raw) <= 8:
        return "*" * len(raw)
    return f"{raw[:4]}{'*' * (len(raw) - 8)}{raw[-4:]}"


def _mask_bank_card(match: re.Match[str]) -> str:
    return _mask_digits(match.group(1))


def _mask_cn_id(match: re.Match[str]) -> str:
    raw = match.group(1)
    return f"{raw[:3]}***********{raw[-4:]}"


def _redact_string(text: str) -> str:
    out = _BANK_CARD_RE.sub(_mask_bank_card, text)
    out = _CN_ID_RE.sub(_mask_cn_id, out)
    out = _OPENAI_KEY_RE.sub("[REDACTED_KEY]", out)
    out = _BEARER_TOKEN_RE.sub(r"\1[REDACTED_TOKEN]", out)
    return out


def redact_sensitive_content(content: Any) -> Any:
    # 递归处理嵌套 JSON/list/tuple，保证工具返回结构不变，只替换敏感值本身。
    if isinstance(content, str):
        return _redact_string(content)
    if isinstance(content, list):
        return [redact_sensitive_content(item) for item in content]
    if isinstance(content, tuple):
        return tuple(redact_sensitive_content(item) for item in content)
    if isinstance(content, dict):
        return {
            key: redact_sensitive_content(value)
            for key, value in content.items()
        }
    return content
