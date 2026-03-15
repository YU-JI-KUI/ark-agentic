"""
Memory 模块 - 记忆系统

提供 SQLite 后端的向量存储、FTS5 关键词搜索、混合检索等功能。
"""

from .types import MemoryChunk, MemorySearchResult
from .sqlite_store import SQLiteMemoryStore, SQLiteStoreConfig
from .chunker import MarkdownChunker
from .embeddings import BGEEmbedding
from .manager import MemoryManager, MemoryConfig

__all__ = [
    "MemoryChunk",
    "MemorySearchResult",
    "MemoryConfig",
    "SQLiteMemoryStore",
    "SQLiteStoreConfig",
    "MarkdownChunker",
    "BGEEmbedding",
    "MemoryManager",
]
