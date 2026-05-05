"""File backend - default storage implementations.

每个 ``FileXxxRepository`` 自己拥有所有文件 I/O；早期的中间类
（TranscriptManager / SessionStore / NotificationStore）已被合并删除。
JSONL 编解码在 ``core.session.format``，FileLock 在 ``._lock``；
SQLite 后端的 raw transcript 路径复用 ``core.session.format``。
``MemoryCache`` 在 ``core.storage.inproc_cache``（与文件后端无关）。
"""

from .memory import FileMemoryRepository
from .session import FileSessionRepository

__all__ = [
    "FileMemoryRepository",
    "FileSessionRepository",
]
