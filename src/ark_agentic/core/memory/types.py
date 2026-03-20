"""
Memory 系统类型定义

参考: openclaw-main/src/memory/types.ts
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Protocol


class MemorySource(str, Enum):
    """记忆来源"""

    MEMORY = "memory"  # 长期记忆文件 (MEMORY.md, memory/*.md)
    SESSIONS = "sessions"  # 会话转录
    KNOWLEDGE = "knowledge"  # 知识库文档


@dataclass
class MemoryChunk:
    """记忆片段"""

    id: str
    path: str  # 文件路径
    start_line: int
    end_line: int
    text: str  # 原文内容
    source: MemorySource = MemorySource.MEMORY
    user_id: str = ""  # 用户标识（shared DB 分区）
    embedding: list[float] | None = None  # 向量表示
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def content_hash(self) -> str:
        """内容哈希（用于去重和增量更新）"""
        import hashlib

        return hashlib.md5(self.text.encode()).hexdigest()


@dataclass
class MemorySearchResult:
    """搜索结果"""

    path: str
    start_line: int
    end_line: int
    score: float  # 综合得分 (0-1)
    snippet: str  # 匹配片段
    source: MemorySource
    citation: str | None = None  # 引用格式 (path#line)

    # 分项得分（用于调试）
    vector_score: float = 0.0
    keyword_score: float = 0.0

    @classmethod
    def from_chunk(
        cls,
        chunk: MemoryChunk,
        score: float,
        vector_score: float = 0.0,
        keyword_score: float = 0.0,
    ) -> MemorySearchResult:
        """从 chunk 创建搜索结果"""
        return cls(
            path=chunk.path,
            start_line=chunk.start_line,
            end_line=chunk.end_line,
            score=score,
            snippet=chunk.text[:500] + ("..." if len(chunk.text) > 500 else ""),
            source=chunk.source,
            citation=f"{chunk.path}#{chunk.start_line}",
            vector_score=vector_score,
            keyword_score=keyword_score,
        )


@dataclass
class MemoryFileEntry:
    """记忆文件条目"""

    path: str  # 相对路径
    abs_path: str  # 绝对路径
    mtime_ms: float  # 修改时间
    size: int  # 文件大小
    content_hash: str  # 内容哈希
    source: MemorySource = MemorySource.MEMORY


@dataclass
class MemorySyncProgress:
    """同步进度"""

    completed: int
    total: int
    label: str = ""


@dataclass
class MemoryStatus:
    """Memory 系统状态"""

    # 基础信息
    workspace_dir: str
    index_path: str | None = None

    # 统计
    total_files: int = 0
    total_chunks: int = 0

    # Embedding
    embedding_model: str = ""
    embedding_dims: int = 0

    # 向量存储
    vector_enabled: bool = False
    vector_backend: str = "sqlite-vec"

    # 关键词搜索
    keyword_enabled: bool = False
    keyword_backend: str = "fts5+jieba"

    # 缓存
    cache_enabled: bool = False
    cache_entries: int = 0

    # 来源统计
    source_counts: dict[str, int] = field(default_factory=dict)

    # 最后同步时间
    last_sync_at: datetime | None = None


# ============ 协议定义 ============


class EmbeddingProvider(Protocol):
    """Embedding 提供者协议"""

    @property
    def model_name(self) -> str:
        """模型名称"""
        ...

    @property
    def dimensions(self) -> int:
        """向量维度"""
        ...

    async def embed_query(self, text: str) -> list[float]:
        """嵌入查询文本"""
        ...

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """批量嵌入文本"""
        ...


class VectorStore(Protocol):
    """向量存储协议"""

    def add(self, chunks: list[MemoryChunk]) -> None:
        """添加向量"""
        ...

    def search(
        self, query_vector: list[float], top_k: int = 10
    ) -> list[tuple[MemoryChunk, float]]:
        """向量搜索"""
        ...

    def delete(self, ids: list[str]) -> None:
        """删除向量"""
        ...

    def save(self, path: str) -> None:
        """保存索引"""
        ...

    def load(self, path: str) -> None:
        """加载索引"""
        ...

    @property
    def size(self) -> int:
        """索引大小"""
        ...


class KeywordSearcher(Protocol):
    """关键词搜索协议"""

    def index(self, chunks: list[MemoryChunk]) -> None:
        """索引文档"""
        ...

    def search(
        self, query: str, top_k: int = 10
    ) -> list[tuple[MemoryChunk, float]]:
        """关键词搜索"""
        ...

    def clear(self) -> None:
        """清空索引"""
        ...


class MemorySearchManager(Protocol):
    """Memory 搜索管理器协议"""

    async def search(
        self,
        query: str,
        max_results: int = 10,
        min_score: float = 0.0,
        sources: list[MemorySource] | None = None,
    ) -> list[MemorySearchResult]:
        """搜索记忆"""
        ...

    async def sync(
        self,
        force: bool = False,
        progress_callback: callable | None = None,
    ) -> None:
        """同步索引"""
        ...

    def status(self) -> MemoryStatus:
        """获取状态"""
        ...

    async def close(self) -> None:
        """关闭管理器"""
        ...
