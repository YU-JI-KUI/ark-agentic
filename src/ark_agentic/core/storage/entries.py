"""Backend-neutral storage DTOs.

Lives outside of any backend (``backends/file``, ``backends/sqlite``) so the
data model carries no file-system semantics. The shape is what the protocols
exchange with their callers; the file backend serialises it to JSON, the
SQLite backend stores it across columns.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SessionStoreEntry:
    """Per-session metadata exchanged between repositories and callers.

    Reference: openclaw ``SessionEntry``. No backend-specific fields here —
    file paths, row IDs, etc. live entirely inside the backend implementation.
    """

    session_id: str
    updated_at: int  # 毫秒时间戳
    model: str = "Qwen3-80B-Instruct"
    provider: str = "ark"
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    compaction_count: int = 0
    active_skill_ids: list[str] = field(default_factory=list)
    state: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sessionId": self.session_id,
            "updatedAt": self.updated_at,
            "model": self.model,
            "provider": self.provider,
            "inputTokens": self.prompt_tokens,
            "outputTokens": self.completion_tokens,
            "totalTokens": self.total_tokens,
            "compactionCount": self.compaction_count,
            "activeSkillIds": self.active_skill_ids,
            "state": self.state,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SessionStoreEntry:
        return cls(
            session_id=data.get("sessionId", ""),
            updated_at=data.get("updatedAt", 0),
            model=data.get("model", "Qwen3-80B-Instruct"),
            provider=data.get("provider", "ark"),
            prompt_tokens=data.get("inputTokens", 0),
            completion_tokens=data.get("outputTokens", 0),
            total_tokens=data.get("totalTokens", 0),
            compaction_count=data.get("compactionCount", 0),
            active_skill_ids=data.get("activeSkillIds", []),
            state=data.get("state", {}),
        )
