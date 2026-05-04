"""File backend - default storage implementations.

每个 ``FileXxxRepository`` 自己拥有所有文件 I/O；早期的中间类
（TranscriptManager / SessionStore / NotificationStore）已被合并删除。
JSONL 解析 / FileLock / 序列化等共享工具仍在 ``core.persistence`` 中，
SQLite 后端的 raw transcript 路径也复用它们。
``MemoryCache`` 在 ``core.storage.inproc_cache``（与文件后端无关）。
"""

from .agent_state import FileAgentStateRepository
from .memory import FileMemoryRepository
from .session import FileSessionRepository

__all__ = [
    "FileAgentStateRepository",
    "FileMemoryRepository",
    "FileSessionRepository",
]
