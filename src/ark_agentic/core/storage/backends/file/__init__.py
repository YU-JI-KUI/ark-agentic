"""File backend - default storage implementations.

直接落盘到 transcript JSONL、sessions.json、MEMORY.md、.last_* 标记文件。
基于现有 TranscriptManager / SessionStore / NotificationStore 包装。
``MemoryCache`` 已迁出到 ``core.storage.inproc_cache`` —— 它和文件后端无关。
"""

from .agent_state import FileAgentStateRepository
from .memory import FileMemoryRepository
from .notification import FileNotificationRepository
from .session import FileSessionRepository

__all__ = [
    "FileAgentStateRepository",
    "FileMemoryRepository",
    "FileNotificationRepository",
    "FileSessionRepository",
]
