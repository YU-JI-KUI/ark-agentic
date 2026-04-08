"""Memory 模块 — 用户记忆生命周期管理

Session JSONL (raw) → MEMORY.md (distilled) → System Prompt (consumption)。
"""

from .manager import MemoryManager, MemoryConfig

__all__ = [
    "MemoryConfig",
    "MemoryManager",
]
