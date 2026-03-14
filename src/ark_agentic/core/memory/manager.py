"""
Memory 管理器

统一管理向量存储、关键词搜索和文档同步。

参考: openclaw-main/src/memory/manager.ts
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .chunker import ChunkConfig, MarkdownChunker
from .embeddings import BGEConfig, BGEEmbedding
from .hybrid import HybridConfig, HybridSearcher
from .keyword_search import BM25Config, JiebaBM25Searcher
from .types import (
    MemoryChunk,
    MemorySearchResult,
    MemorySource,
    MemoryStatus,
    MemorySyncProgress,
)
from .vector_store import FAISSConfig, FAISSVectorStore

logger = logging.getLogger(__name__)


@dataclass
class MemoryConfig:
    """Memory 系统配置"""

    workspace_dir: str = ""
    index_dir: str = ""

    memory_paths: list[str] = field(
        default_factory=lambda: ["MEMORY.md", "memory/"]
    )

    # File-based engine components
    embedding: BGEConfig = field(default_factory=BGEConfig)
    vector: FAISSConfig = field(default_factory=FAISSConfig)
    keyword: BM25Config = field(default_factory=BM25Config)
    hybrid: HybridConfig = field(default_factory=HybridConfig)
    chunk: ChunkConfig = field(default_factory=ChunkConfig)

    auto_sync: bool = True
    sync_on_init: bool = True
    watch_files: bool = False


class MemoryManager:
    """Memory 管理器

    提供统一的记忆管理接口，包括：
    - 文档索引和同步
    - 向量/关键词/混合搜索
    - 持久化存储
    """

    def __init__(self, config: MemoryConfig) -> None:
        self.config = config
        self._workspace_dir = Path(config.workspace_dir)
        self._index_dir = (
            Path(config.index_dir)
            if config.index_dir
            else self._workspace_dir / ".memory"
        )

        self._embedding: BGEEmbedding | None = None
        self._vector_store: FAISSVectorStore | None = None
        self._keyword_searcher: JiebaBM25Searcher | None = None
        self._hybrid_searcher: HybridSearcher | None = None
        self._chunker: MarkdownChunker | None = None

        self._initialized = False
        self._last_sync: datetime | None = None
        self._file_hashes: dict[str, str] = {}

    async def initialize(self) -> None:
        if self._initialized:
            return

        await self._initialize_file_engine()

        self._initialized = True
        logger.info("Memory system initialized")

    async def _initialize_file_engine(self) -> None:
        logger.info(f"Initializing Memory system at {self._workspace_dir}")

        self._index_dir.mkdir(parents=True, exist_ok=True)
        self._embedding = BGEEmbedding(self.config.embedding)

        dimensions = self._embedding.dimensions
        if dimensions == 0:
            _ = await self._embedding.embed_query("test")
            dimensions = self._embedding.dimensions

        self._vector_store = FAISSVectorStore(dimensions, self.config.vector)
        self._keyword_searcher = JiebaBM25Searcher(self.config.keyword)
        self._hybrid_searcher = HybridSearcher(
            self._vector_store,
            self._keyword_searcher,
            self._embedding,
            self.config.hybrid,
        )
        self._chunker = MarkdownChunker(self.config.chunk)

        await self._load_index()

        if self.config.sync_on_init:
            self._initialized = True
            await self.sync()

    async def _load_index(self) -> bool:
        """加载已有索引"""
        index_path = self._index_dir / "memory_index"

        try:
            if (index_path.with_suffix(".faiss")).exists():
                self._vector_store.load(str(index_path))

                # 重建关键词索引
                chunks = self._vector_store.get_all_chunks()
                self._keyword_searcher.index(chunks)

                logger.info(f"Loaded existing index with {len(chunks)} chunks")
                return True
        except Exception as e:
            logger.warning(f"Failed to load index: {e}")

        return False

    async def sync(
        self,
        force: bool = False,
        progress_callback: Callable[[MemorySyncProgress], None] | None = None,
    ) -> None:
        """同步索引

        扫描 memory 文件，更新有变化的文档。

        Args:
            force: 强制完全重建索引
            progress_callback: 进度回调
        """
        if not self._initialized and not force:
            await self.initialize()
            return

        logger.info(f"Syncing memory index (force={force})")

        # 收集需要索引的文件
        files_to_index: list[tuple[Path, MemorySource]] = []

        for memory_path in self.config.memory_paths:
            full_path = self._workspace_dir / memory_path

            if full_path.is_file():
                files_to_index.append((full_path, MemorySource.MEMORY))
            elif full_path.is_dir():
                for file_path in full_path.rglob("*.md"):
                    files_to_index.append((file_path, MemorySource.MEMORY))

        total = len(files_to_index)
        if progress_callback:
            progress_callback(MemorySyncProgress(0, total, "Scanning files"))

        # 检查变化并索引
        new_chunks: list[MemoryChunk] = []
        changed_files = 0

        for i, (file_path, source) in enumerate(files_to_index):
            # 检查文件是否变化
            try:
                content = file_path.read_text(encoding="utf-8")
                content_hash = hashlib.md5(content.encode()).hexdigest()
            except Exception as e:
                logger.warning(f"Failed to read {file_path}: {e}")
                continue

            rel_path = str(file_path.relative_to(self._workspace_dir))
            old_hash = self._file_hashes.get(rel_path)

            if not force and old_hash == content_hash:
                continue  # 文件未变化

            # 分块
            chunks = self._chunker.chunk_text(content, rel_path, source)
            new_chunks.extend(chunks)
            self._file_hashes[rel_path] = content_hash
            changed_files += 1

            if progress_callback:
                progress_callback(
                    MemorySyncProgress(i + 1, total, f"Processing {file_path.name}")
                )

        if not new_chunks:
            logger.info("No changes detected")
            return

        logger.info(f"Indexing {len(new_chunks)} chunks from {changed_files} files")

        # 生成 embeddings
        if progress_callback:
            progress_callback(
                MemorySyncProgress(0, len(new_chunks), "Generating embeddings")
            )

        texts = [c.text for c in new_chunks]
        embeddings = await self._embedding.embed_batch(texts)

        for chunk, embedding in zip(new_chunks, embeddings):
            chunk.embedding = embedding

        # 如果强制重建，清空旧索引
        if force:
            self._vector_store.clear()
            self._keyword_searcher.clear()

        # 添加到索引
        self._vector_store.add(new_chunks)
        self._keyword_searcher.index(new_chunks)

        # 保存索引
        await self._save_index()

        self._last_sync = datetime.now()
        logger.info(
            f"Sync complete: {len(new_chunks)} chunks, "
            f"vector={self._vector_store.size}, keyword={self._keyword_searcher.size}"
        )

    async def _save_index(self) -> None:
        """保存索引"""
        index_path = self._index_dir / "memory_index"

        try:
            self._vector_store.save(str(index_path))
            logger.debug(f"Saved index to {index_path}")
        except Exception as e:
            logger.error(f"Failed to save index: {e}")

    async def search(
        self,
        query: str,
        max_results: int = 10,
        min_score: float = 0.0,
        sources: list[MemorySource] | None = None,
        search_mode: str = "hybrid",
        user_id: str = "",
    ) -> list[MemorySearchResult]:
        if not self._initialized:
            await self.initialize()

        results = await self._hybrid_searcher.search(
            query,
            top_k=max_results,
            min_score=min_score,
            vector_only=(search_mode == "vector"),
            keyword_only=(search_mode == "keyword"),
        )

        if sources:
            results = [r for r in results if r.source in sources]

        return results[:max_results]

    def status(self) -> MemoryStatus:
        """获取系统状态"""
        source_counts: dict[str, int] = {}

        if self._vector_store:
            for chunk in self._vector_store.get_all_chunks():
                source = chunk.source.value
                source_counts[source] = source_counts.get(source, 0) + 1

        return MemoryStatus(
            workspace_dir=str(self._workspace_dir),
            index_path=str(self._index_dir),
            total_files=len(self._file_hashes),
            total_chunks=self._vector_store.chunk_count if self._vector_store else 0,
            embedding_model=self.config.embedding.model_name,
            embedding_dims=self._embedding.dimensions if self._embedding else 0,
            vector_enabled=True,
            vector_backend="faiss",
            keyword_enabled=True,
            keyword_backend="bm25",
            source_counts=source_counts,
            last_sync_at=self._last_sync,
        )

    async def add_document(
        self,
        content: str,
        path: str,
        source: MemorySource = MemorySource.MEMORY,
    ) -> int:
        """手动添加文档

        Args:
            content: 文档内容
            path: 文档路径（标识用）
            source: 来源类型

        Returns:
            添加的 chunk 数量
        """
        if not self._initialized:
            await self.initialize()

        # 分块
        chunks = self._chunker.chunk_text(content, path, source)
        if not chunks:
            return 0

        # 生成 embeddings
        texts = [c.text for c in chunks]
        embeddings = await self._embedding.embed_batch(texts)

        for chunk, embedding in zip(chunks, embeddings):
            chunk.embedding = embedding

        # 添加到索引
        self._vector_store.add(chunks)
        self._keyword_searcher.index(chunks)

        logger.info(f"Added {len(chunks)} chunks from {path}")
        return len(chunks)

    async def close(self) -> None:
        """关闭管理器"""
        if self._vector_store:
            await self._save_index()

        self._initialized = False
        logger.info("Memory system closed")


# ============ 便捷函数 ============


def create_memory_manager(
    workspace_dir: str,
    embedding_model: str = "",
    device: str = "cpu",
) -> MemoryManager:
    """创建 Memory 管理器"""
    config = MemoryConfig(
        workspace_dir=workspace_dir,
        embedding=BGEConfig(model_name=embedding_model, device=device),
    )
    return MemoryManager(config)


async def quick_search(
    workspace_dir: str,
    query: str,
    max_results: int = 10,
) -> list[MemorySearchResult]:
    """快速搜索（一次性使用）"""
    manager = create_memory_manager(workspace_dir)
    await manager.initialize()

    try:
        return await manager.search(query, max_results=max_results)
    finally:
        await manager.close()
