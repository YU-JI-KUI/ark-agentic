"""
混合检索

结合向量相似度搜索和关键词搜索，使用加权融合得到最终结果。

参考: openclaw-main/src/memory/hybrid.ts
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .types import MemoryChunk, MemorySearchResult

logger = logging.getLogger(__name__)


@dataclass
class HybridConfig:
    """混合检索配置"""

    # 权重配置
    vector_weight: float = 0.7  # 向量搜索权重
    keyword_weight: float = 0.3  # 关键词搜索权重

    # 结果数量
    vector_top_k: int = 20  # 向量搜索取 top_k
    keyword_top_k: int = 20  # 关键词搜索取 top_k

    # 分数阈值
    min_score: float = 0.1  # 最低分数阈值

    # 去重
    dedupe_by_content: bool = True  # 按内容去重


def merge_hybrid_results(
    vector_results: list[tuple[MemoryChunk, float]],
    keyword_results: list[tuple[MemoryChunk, float]],
    config: HybridConfig | None = None,
) -> list[MemorySearchResult]:
    """合并向量搜索和关键词搜索结果

    使用加权融合：
    final_score = vector_weight * vector_score + keyword_weight * keyword_score

    Args:
        vector_results: 向量搜索结果 [(chunk, score), ...]
        keyword_results: 关键词搜索结果 [(chunk, score), ...]
        config: 混合检索配置

    Returns:
        合并后的搜索结果，按分数降序排列
    """
    config = config or HybridConfig()

    # 构建 ID -> 结果 的映射
    merged: dict[str, dict] = {}

    # 处理向量搜索结果
    for chunk, score in vector_results:
        merged[chunk.id] = {
            "chunk": chunk,
            "vector_score": score,
            "keyword_score": 0.0,
        }

    # 处理关键词搜索结果
    for chunk, score in keyword_results:
        if chunk.id in merged:
            merged[chunk.id]["keyword_score"] = score
        else:
            merged[chunk.id] = {
                "chunk": chunk,
                "vector_score": 0.0,
                "keyword_score": score,
            }

    # 计算最终分数
    results: list[MemorySearchResult] = []
    seen_content: set[str] = set()

    for entry in merged.values():
        chunk = entry["chunk"]
        vector_score = entry["vector_score"]
        keyword_score = entry["keyword_score"]

        # 加权融合
        final_score = (
            config.vector_weight * vector_score
            + config.keyword_weight * keyword_score
        )

        # 分数过滤
        if final_score < config.min_score:
            continue

        # 内容去重
        if config.dedupe_by_content:
            content_key = chunk.content_hash
            if content_key in seen_content:
                continue
            seen_content.add(content_key)

        results.append(
            MemorySearchResult.from_chunk(
                chunk,
                score=final_score,
                vector_score=vector_score,
                keyword_score=keyword_score,
            )
        )

    # 按分数降序排序
    results.sort(key=lambda x: x.score, reverse=True)

    return results


class HybridSearcher:
    """混合检索器

    封装向量存储和关键词搜索器，提供统一的搜索接口。
    """

    def __init__(
        self,
        vector_store,  # FAISSVectorStore
        keyword_searcher,  # JiebaBM25Searcher
        embedding_provider,  # BGEEmbedding
        config: HybridConfig | None = None,
    ) -> None:
        self.vector_store = vector_store
        self.keyword_searcher = keyword_searcher
        self.embedding_provider = embedding_provider
        self.config = config or HybridConfig()

    async def search(
        self,
        query: str,
        top_k: int = 10,
        min_score: float | None = None,
        vector_only: bool = False,
        keyword_only: bool = False,
    ) -> list[MemorySearchResult]:
        """混合搜索

        Args:
            query: 查询文本
            top_k: 返回结果数量
            min_score: 最低分数阈值
            vector_only: 仅使用向量搜索
            keyword_only: 仅使用关键词搜索

        Returns:
            搜索结果列表
        """
        vector_results: list[tuple[MemoryChunk, float]] = []
        keyword_results: list[tuple[MemoryChunk, float]] = []

        # 向量搜索
        if not keyword_only and self.vector_store.size > 0:
            query_embedding = await self.embedding_provider.embed_query(query)
            vector_results = self.vector_store.search(
                query_embedding, top_k=self.config.vector_top_k
            )

        # 关键词搜索
        if not vector_only and self.keyword_searcher.size > 0:
            keyword_results = self.keyword_searcher.search(
                query, top_k=self.config.keyword_top_k
            )

        # 处理单一搜索模式
        if vector_only:
            results = [
                MemorySearchResult.from_chunk(chunk, score, vector_score=score)
                for chunk, score in vector_results
            ]
        elif keyword_only:
            results = [
                MemorySearchResult.from_chunk(chunk, score, keyword_score=score)
                for chunk, score in keyword_results
            ]
        else:
            # 混合合并
            config = HybridConfig(
                vector_weight=self.config.vector_weight,
                keyword_weight=self.config.keyword_weight,
                min_score=min_score or self.config.min_score,
            )
            results = merge_hybrid_results(
                vector_results, keyword_results, config
            )

        # 返回 top_k
        return results[:top_k]

    def search_sync(
        self,
        query: str,
        query_embedding: list[float],
        top_k: int = 10,
        min_score: float | None = None,
    ) -> list[MemorySearchResult]:
        """同步混合搜索（需要预先计算 query_embedding）"""
        # 向量搜索
        vector_results = self.vector_store.search(
            query_embedding, top_k=self.config.vector_top_k
        )

        # 关键词搜索
        keyword_results = self.keyword_searcher.search(
            query, top_k=self.config.keyword_top_k
        )

        # 混合合并
        config = HybridConfig(
            vector_weight=self.config.vector_weight,
            keyword_weight=self.config.keyword_weight,
            min_score=min_score or self.config.min_score,
        )
        results = merge_hybrid_results(vector_results, keyword_results, config)

        return results[:top_k]


# ============ 便捷函数 ============


def create_hybrid_searcher(
    vector_store,
    keyword_searcher,
    embedding_provider,
    vector_weight: float = 0.7,
    keyword_weight: float = 0.3,
) -> HybridSearcher:
    """创建混合检索器"""
    config = HybridConfig(
        vector_weight=vector_weight,
        keyword_weight=keyword_weight,
    )
    return HybridSearcher(
        vector_store, keyword_searcher, embedding_provider, config
    )
