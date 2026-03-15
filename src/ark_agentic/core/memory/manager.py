"""
Memory 管理器

统一管理 SQLiteMemoryStore、文档同步和搜索。

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
from .sqlite_store import IndexMeta, SQLiteMemoryStore, SQLiteStoreConfig
from .types import (
    MemoryChunk,
    MemorySearchResult,
    MemorySource,
    MemoryStatus,
    MemorySyncProgress,
)

logger = logging.getLogger(__name__)


@dataclass
class MemoryConfig:
    """Memory 系统配置"""

    workspace_dir: str = ""
    index_dir: str = ""

    memory_paths: list[str] = field(
        default_factory=lambda: ["MEMORY.md", "memory/"]
    )

    embedding: BGEConfig = field(default_factory=BGEConfig)
    store: SQLiteStoreConfig = field(default_factory=SQLiteStoreConfig)
    chunk: ChunkConfig = field(default_factory=ChunkConfig)

    auto_sync: bool = True
    sync_on_init: bool = True
    watch_files: bool = False


class MemoryManager:
    """Memory 管理器

    提供统一的记忆管理接口，包括：
    - 文档索引和同步（SQLite 后端）
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
        self._store: SQLiteMemoryStore | None = None
        self._chunker: MarkdownChunker | None = None

        self._initialized = False
        self._last_sync: datetime | None = None
        self._syncing: asyncio.Task[None] | None = None

    async def initialize(self) -> None:
        if self._initialized:
            return

        await self._initialize_file_engine()

        self._initialized = True
        logger.info("Memory system initialized")

    async def _initialize_file_engine(self) -> None:
        logger.info("Initializing Memory system at %s", self._workspace_dir)

        self._index_dir.mkdir(parents=True, exist_ok=True)
        self._embedding = BGEEmbedding(self.config.embedding)

        dimensions = self._embedding.dimensions
        if dimensions == 0:
            _ = await self._embedding.embed_query("test")
            dimensions = self._embedding.dimensions

        db_path = str(self._index_dir / self.config.store.db_name)
        self._store = SQLiteMemoryStore(db_path, self.config.store, dimensions)
        self._store._ensure_vector_table(dimensions)

        self._chunker = MarkdownChunker(self.config.chunk)

        if self.config.sync_on_init:
            self._initialized = True
            await self.sync()

    def _build_current_meta(self) -> IndexMeta:
        return IndexMeta(
            model=self.config.embedding.model_name,
            dims=self._embedding.dimensions if self._embedding else 0,
            chunk_size=self.config.chunk.chunk_size,
            chunk_overlap=self.config.chunk.chunk_overlap,
        )

    def _needs_full_reindex(self, current_meta: IndexMeta) -> bool:
        stored = self._store.read_meta()
        if stored is None:
            return True
        return (
            stored.model != current_meta.model
            or stored.dims != current_meta.dims
            or stored.chunk_size != current_meta.chunk_size
            or stored.chunk_overlap != current_meta.chunk_overlap
        )

    async def sync(
        self,
        force: bool = False,
        progress_callback: Callable[[MemorySyncProgress], None] | None = None,
    ) -> None:
        if not self._initialized and not force:
            await self.initialize()
            return

        # Sync mutex
        if self._syncing is not None:
            try:
                await self._syncing
            except Exception:
                pass
            return

        self._syncing = asyncio.ensure_future(
            self._run_sync(force, progress_callback)
        )
        try:
            await self._syncing
        finally:
            self._syncing = None

    async def _run_sync(
        self,
        force: bool = False,
        progress_callback: Callable[[MemorySyncProgress], None] | None = None,
    ) -> None:
        logger.info("Syncing memory index (force=%s)", force)

        current_meta = self._build_current_meta()
        need_full = force or self._needs_full_reindex(current_meta)

        # Collect files
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

        new_chunks: list[MemoryChunk] = []
        changed_paths: list[str] = []

        for i, (file_path, source) in enumerate(files_to_index):
            try:
                content = file_path.read_text(encoding="utf-8")
                content_hash = hashlib.md5(content.encode()).hexdigest()
            except Exception as e:
                logger.warning("Failed to read %s: %s", file_path, e)
                continue

            rel_path = str(file_path.relative_to(self._workspace_dir))

            if not need_full:
                old_hash = self._store.get_file_hash(rel_path)
                if old_hash == content_hash:
                    continue

            chunks = self._chunker.chunk_text(content, rel_path, source)
            new_chunks.extend(chunks)
            changed_paths.append(rel_path)

            stat = file_path.stat()
            self._store.set_file_hash(
                rel_path, content_hash, source.value,
                mtime_ms=stat.st_mtime * 1000, size=stat.st_size,
            )

            if progress_callback:
                progress_callback(
                    MemorySyncProgress(i + 1, total, f"Processing {file_path.name}")
                )

        if not new_chunks:
            if need_full:
                self._store.write_meta(current_meta)
            logger.info("No changes detected")
            return

        logger.info("Indexing %d chunks from %d files", len(new_chunks), len(changed_paths))

        if progress_callback:
            progress_callback(
                MemorySyncProgress(0, len(new_chunks), "Generating embeddings")
            )

        # Embedding with cache
        model_name = self.config.embedding.model_name
        content_hashes = [c.content_hash for c in new_chunks]
        cached = self._store.get_cached_embeddings(model_name, content_hashes)

        uncached_indices: list[int] = []
        for idx, chunk in enumerate(new_chunks):
            h = chunk.content_hash
            if h in cached:
                chunk.embedding = cached[h]
            else:
                uncached_indices.append(idx)

        if uncached_indices:
            texts = [new_chunks[i].text for i in uncached_indices]
            embeddings = await self._embedding.embed_batch(texts)
            cache_entries: list[tuple[str, list[float]]] = []
            for j, idx in enumerate(uncached_indices):
                new_chunks[idx].embedding = embeddings[j]
                cache_entries.append((new_chunks[idx].content_hash, embeddings[j]))
            self._store.set_cached_embeddings(model_name, cache_entries)

        if need_full:
            self._store.safe_reindex(new_chunks, current_meta)
        else:
            for path in changed_paths:
                self._store.delete_by_path(path)
            self._store.add(new_chunks)
            self._store.write_meta(current_meta)

        self._last_sync = datetime.now()
        logger.info(
            "Sync complete: %d chunks, store size=%d",
            len(new_chunks), self._store.size,
        )

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

        query_embedding = await self._embedding.embed_query(query)

        if search_mode == "vector":
            raw = self._store.vector_search(query_embedding, max_results)
            results = [
                MemorySearchResult.from_chunk(chunk, score, vector_score=score)
                for chunk, score in raw
            ]
        elif search_mode == "keyword":
            raw = self._store.keyword_search(query, max_results)
            results = [
                MemorySearchResult.from_chunk(chunk, score, keyword_score=score)
                for chunk, score in raw
            ]
        else:
            results = self._store.hybrid_search(
                query, query_embedding,
                top_k=max_results, min_score=min_score,
            )

        if sources:
            results = [r for r in results if r.source in sources]

        return results[:max_results]

    def status(self) -> MemoryStatus:
        source_counts: dict[str, int] = {}

        if self._store:
            for chunk in self._store.get_all_chunks():
                source = chunk.source.value
                source_counts[source] = source_counts.get(source, 0) + 1

        return MemoryStatus(
            workspace_dir=str(self._workspace_dir),
            index_path=str(self._index_dir),
            total_files=0,
            total_chunks=self._store.chunk_count if self._store else 0,
            embedding_model=self.config.embedding.model_name,
            embedding_dims=self._embedding.dimensions if self._embedding else 0,
            vector_enabled=True,
            vector_backend="sqlite-vec",
            keyword_enabled=True,
            keyword_backend="fts5+jieba",
            source_counts=source_counts,
            last_sync_at=self._last_sync,
        )

    async def add_document(
        self,
        content: str,
        path: str,
        source: MemorySource = MemorySource.MEMORY,
    ) -> int:
        if not self._initialized:
            await self.initialize()

        chunks = self._chunker.chunk_text(content, path, source)
        if not chunks:
            return 0

        texts = [c.text for c in chunks]
        embeddings = await self._embedding.embed_batch(texts)

        for chunk, embedding in zip(chunks, embeddings):
            chunk.embedding = embedding

        self._store.add(chunks)

        logger.info("Added %d chunks from %s", len(chunks), path)
        return len(chunks)

    async def close(self) -> None:
        if self._store:
            self._store.close()

        self._initialized = False
        logger.info("Memory system closed")


# ============ 便捷函数 ============


def build_memory_manager(memory_dir: str | Path | None = None) -> MemoryManager:
    """Build a MemoryManager with directory setup and MEMORY.md seed.

    Falls back to a temp directory if memory_dir is None.
    """
    import tempfile

    if memory_dir is None:
        memory_dir = Path(tempfile.gettempdir()) / "ark_memory"
    memory_dir = Path(memory_dir)
    memory_dir.mkdir(parents=True, exist_ok=True)

    seed_file = memory_dir / "MEMORY.md"
    if not seed_file.exists():
        seed_file.write_text(
            "# Agent Memory\n\n此文件用于存储跨会话的长期记忆。\n",
            encoding="utf-8",
        )

    # index_dir intentionally omitted: MemoryManager defaults to workspace_dir/.memory,
    # which allows _get_memory_for_user to correctly scope per-user DBs.
    config = MemoryConfig(workspace_dir=str(memory_dir))
    logger.info("Memory enabled: workspace=%s", memory_dir)
    return MemoryManager(config)


def create_memory_manager(
    workspace_dir: str,
    embedding_model: str = "",
    device: str = "cpu",
) -> MemoryManager:
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
    manager = create_memory_manager(workspace_dir)
    await manager.initialize()

    try:
        return await manager.search(query, max_results=max_results)
    finally:
        await manager.close()
