"""
FAISS 向量存储

使用 FAISS 实现高效的向量相似度搜索。
"""

from __future__ import annotations

import logging
import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from .types import MemoryChunk

logger = logging.getLogger(__name__)


@dataclass
class FAISSConfig:
    """FAISS 配置"""

    # 索引类型
    # - "flat": 精确搜索，适合小数据集 (<10k)
    # - "ivf": 倒排索引，适合中等数据集
    # - "hnsw": HNSW 图索引，速度最快
    index_type: str = "flat"

    # IVF 参数
    nlist: int = 100  # 聚类数量
    nprobe: int = 10  # 搜索时探测的聚类数

    # HNSW 参数
    hnsw_m: int = 32  # 每个节点的连接数
    hnsw_ef_construction: int = 200  # 构建时的搜索范围
    hnsw_ef_search: int = 64  # 搜索时的搜索范围

    # 是否使用内积（用于归一化向量的余弦相似度）
    use_inner_product: bool = True


class FAISSVectorStore:
    """FAISS 向量存储

    支持多种索引类型，提供向量的增删改查功能。
    """

    def __init__(
        self,
        dimensions: int,
        config: FAISSConfig | None = None,
    ) -> None:
        self.dimensions = dimensions
        self.config = config or FAISSConfig()

        self._index: Any = None
        self._chunks: dict[str, MemoryChunk] = {}  # id -> chunk
        self._id_to_idx: dict[str, int] = {}  # chunk_id -> faiss_idx
        self._idx_to_id: dict[int, str] = {}  # faiss_idx -> chunk_id

        self._ensure_faiss()
        self._build_index()

    def _ensure_faiss(self) -> None:
        """确保 FAISS 可用"""
        try:
            import faiss

            self._faiss = faiss
        except ImportError:
            raise ImportError(
                "faiss is required. Install with: pip install faiss-cpu"
            )

    def _build_index(self) -> None:
        """构建 FAISS 索引"""
        faiss = self._faiss

        # 选择距离度量
        if self.config.use_inner_product:
            # 内积（对于 L2 归一化的向量等价于余弦相似度）
            metric = faiss.METRIC_INNER_PRODUCT
        else:
            metric = faiss.METRIC_L2

        # 构建索引
        if self.config.index_type == "flat":
            if self.config.use_inner_product:
                self._index = faiss.IndexFlatIP(self.dimensions)
            else:
                self._index = faiss.IndexFlatL2(self.dimensions)

        elif self.config.index_type == "ivf":
            # 需要先训练，初始化时创建空索引
            quantizer = faiss.IndexFlatL2(self.dimensions)
            self._index = faiss.IndexIVFFlat(
                quantizer, self.dimensions, self.config.nlist, metric
            )
            self._index.nprobe = self.config.nprobe

        elif self.config.index_type == "hnsw":
            self._index = faiss.IndexHNSWFlat(
                self.dimensions, self.config.hnsw_m, metric
            )
            self._index.hnsw.efConstruction = self.config.hnsw_ef_construction
            self._index.hnsw.efSearch = self.config.hnsw_ef_search

        else:
            raise ValueError(f"Unknown index type: {self.config.index_type}")

        logger.info(
            f"Created FAISS index: type={self.config.index_type}, "
            f"dims={self.dimensions}, metric={'IP' if self.config.use_inner_product else 'L2'}"
        )

    def add(self, chunks: list[MemoryChunk]) -> None:
        """添加向量"""
        if not chunks:
            return

        # 过滤没有 embedding 的 chunks
        valid_chunks = [c for c in chunks if c.embedding is not None]
        if not valid_chunks:
            logger.warning("No chunks with embeddings to add")
            return

        # 准备向量
        vectors = np.array(
            [c.embedding for c in valid_chunks], dtype=np.float32
        )

        # IVF 索引需要训练
        if self.config.index_type == "ivf" and not self._index.is_trained:
            if len(vectors) < self.config.nlist:
                logger.warning(
                    f"Not enough vectors ({len(vectors)}) to train IVF index "
                    f"(need {self.config.nlist}). Using flat index instead."
                )
                # 回退到 flat 索引
                self.config.index_type = "flat"
                self._build_index()
            else:
                self._index.train(vectors)

        # 添加向量
        start_idx = self._index.ntotal
        self._index.add(vectors)

        # 更新映射
        for i, chunk in enumerate(valid_chunks):
            idx = start_idx + i
            self._chunks[chunk.id] = chunk
            self._id_to_idx[chunk.id] = idx
            self._idx_to_id[idx] = chunk.id

        logger.debug(f"Added {len(valid_chunks)} vectors to FAISS index")

    def search(
        self, query_vector: list[float], top_k: int = 10
    ) -> list[tuple[MemoryChunk, float]]:
        """向量搜索

        Returns:
            [(chunk, score), ...] 按分数降序排列
        """
        if self._index.ntotal == 0:
            return []

        # 准备查询向量
        query = np.array([query_vector], dtype=np.float32)

        # 搜索
        k = min(top_k, self._index.ntotal)
        distances, indices = self._index.search(query, k)

        # 转换结果
        results: list[tuple[MemoryChunk, float]] = []
        for i, idx in enumerate(indices[0]):
            if idx == -1:  # FAISS 返回 -1 表示无效结果
                continue

            chunk_id = self._idx_to_id.get(int(idx))
            if chunk_id is None:
                continue

            chunk = self._chunks.get(chunk_id)
            if chunk is None:
                continue

            # 转换距离为相似度分数
            distance = float(distances[0][i])
            if self.config.use_inner_product:
                # 内积直接作为分数（范围通常在 0-1）
                score = distance
            else:
                # L2 距离转换为相似度
                score = 1.0 / (1.0 + distance)

            results.append((chunk, score))

        return results

    def delete(self, ids: list[str]) -> None:
        """删除向量

        注意：FAISS 的删除效率不高，对于频繁删除的场景
        建议定期重建索引。
        """
        # FAISS 不直接支持删除，我们只从映射中移除
        # 被删除的向量仍在索引中但不会被返回
        for chunk_id in ids:
            if chunk_id in self._chunks:
                del self._chunks[chunk_id]
            if chunk_id in self._id_to_idx:
                idx = self._id_to_idx[chunk_id]
                del self._id_to_idx[chunk_id]
                if idx in self._idx_to_id:
                    del self._idx_to_id[idx]

        logger.debug(f"Marked {len(ids)} vectors as deleted")

    def clear(self) -> None:
        """清空索引"""
        self._chunks.clear()
        self._id_to_idx.clear()
        self._idx_to_id.clear()
        self._build_index()
        logger.info("Cleared FAISS index")

    def save(self, path: str) -> None:
        """保存索引到文件"""
        faiss = self._faiss
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        # 保存 FAISS 索引
        index_path = path.with_suffix(".faiss")
        faiss.write_index(self._index, str(index_path))

        # 保存元数据
        meta_path = path.with_suffix(".meta")
        meta = {
            "dimensions": self.dimensions,
            "config": self.config,
            "chunks": self._chunks,
            "id_to_idx": self._id_to_idx,
            "idx_to_id": self._idx_to_id,
        }
        with open(meta_path, "wb") as f:
            pickle.dump(meta, f)

        logger.info(f"Saved FAISS index to {path}")

    def load(self, path: str) -> None:
        """从文件加载索引"""
        faiss = self._faiss
        path = Path(path)

        # 加载 FAISS 索引
        index_path = path.with_suffix(".faiss")
        if not index_path.exists():
            raise FileNotFoundError(f"Index file not found: {index_path}")

        self._index = faiss.read_index(str(index_path))

        # 加载元数据
        meta_path = path.with_suffix(".meta")
        if meta_path.exists():
            with open(meta_path, "rb") as f:
                meta = pickle.load(f)

            self.dimensions = meta.get("dimensions", self.dimensions)
            self.config = meta.get("config", self.config)
            self._chunks = meta.get("chunks", {})
            self._id_to_idx = meta.get("id_to_idx", {})
            self._idx_to_id = meta.get("idx_to_id", {})

        logger.info(
            f"Loaded FAISS index from {path}, "
            f"total={self._index.ntotal}, chunks={len(self._chunks)}"
        )

    @property
    def size(self) -> int:
        """索引中的向量数量"""
        return self._index.ntotal if self._index else 0

    @property
    def chunk_count(self) -> int:
        """有效的 chunk 数量（排除已删除）"""
        return len(self._chunks)

    def get_chunk(self, chunk_id: str) -> MemoryChunk | None:
        """获取 chunk"""
        return self._chunks.get(chunk_id)

    def get_all_chunks(self) -> list[MemoryChunk]:
        """获取所有 chunks"""
        return list(self._chunks.values())


# ============ 便捷函数 ============


def create_faiss_store(
    dimensions: int,
    index_type: str = "flat",
    use_inner_product: bool = True,
) -> FAISSVectorStore:
    """创建 FAISS 向量存储"""
    config = FAISSConfig(
        index_type=index_type,
        use_inner_product=use_inner_product,
    )
    return FAISSVectorStore(dimensions, config)
