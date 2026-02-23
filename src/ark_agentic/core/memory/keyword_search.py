"""
关键词搜索

使用 jieba 分词 + BM25 实现中文关键词搜索。
"""

from __future__ import annotations

import logging
import math
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from .types import MemoryChunk

logger = logging.getLogger(__name__)


@dataclass
class BM25Config:
    """BM25 配置"""

    k1: float = 1.5  # 词频饱和参数
    b: float = 0.75  # 文档长度归一化参数
    epsilon: float = 0.25  # IDF 平滑参数


class JiebaBM25Searcher:
    """基于 jieba 分词的 BM25 搜索器"""

    def __init__(self, config: BM25Config | None = None) -> None:
        self.config = config or BM25Config()
        self._jieba: Optional[Any] = None  # jieba module, kept as Any due to optional dependency

        # 索引数据
        self._chunks: dict[str, MemoryChunk] = {}  # id -> chunk
        self._doc_tokens: dict[str, list[str]] = {}  # id -> tokens
        self._doc_lengths: dict[str, int] = {}  # id -> token count
        self._avg_doc_length: float = 0.0
        self._df: Counter = Counter()  # document frequency
        self._total_docs: int = 0

        self._ensure_jieba()

    def _ensure_jieba(self) -> None:
        """确保 jieba 可用"""
        try:
            import jieba

            self._jieba = jieba
            # 静默模式
            jieba.setLogLevel(logging.WARNING)
        except ImportError:
            raise ImportError(
                "jieba is required for Chinese text search. "
                "Install with: pip install jieba"
            )

    def _tokenize(self, text: str) -> list[str]:
        """分词"""
        # 使用 jieba 分词，过滤停用词和短词
        tokens = self._jieba.lcut(text)
        # 过滤：长度 > 1，且不是纯数字/标点
        tokens = [
            t.lower()
            for t in tokens
            if len(t) > 1 and not t.isdigit() and not self._is_punctuation(t)
        ]
        return tokens

    def _is_punctuation(self, text: str) -> bool:
        """检查是否是标点符号"""
        import string

        punctuation = string.punctuation + "，。！？、；：""''（）【】《》…—"
        return all(c in punctuation for c in text)

    def index(self, chunks: list[MemoryChunk]) -> None:
        """索引文档"""
        if not chunks:
            return

        for chunk in chunks:
            # 分词
            tokens = self._tokenize(chunk.text)
            if not tokens:
                continue

            # 存储
            self._chunks[chunk.id] = chunk
            self._doc_tokens[chunk.id] = tokens
            self._doc_lengths[chunk.id] = len(tokens)

            # 更新 DF（每个词在文档中是否出现）
            unique_tokens = set(tokens)
            for token in unique_tokens:
                self._df[token] += 1

            self._total_docs += 1

        # 更新平均文档长度
        if self._total_docs > 0:
            self._avg_doc_length = sum(self._doc_lengths.values()) / self._total_docs

        logger.debug(
            f"Indexed {len(chunks)} chunks, "
            f"total={self._total_docs}, vocab={len(self._df)}"
        )

    def _compute_idf(self, term: str) -> float:
        """计算 IDF"""
        df = self._df.get(term, 0)
        if df == 0:
            return 0.0

        # IDF with smoothing
        idf = math.log(
            (self._total_docs - df + 0.5) / (df + 0.5) + 1.0
        )
        return max(idf, self.config.epsilon)

    def _compute_bm25_score(
        self, query_tokens: list[str], doc_id: str
    ) -> float:
        """计算单个文档的 BM25 分数"""
        doc_tokens = self._doc_tokens.get(doc_id, [])
        if not doc_tokens:
            return 0.0

        doc_length = self._doc_lengths.get(doc_id, 0)
        if doc_length == 0:
            return 0.0

        # 文档词频
        tf_counter = Counter(doc_tokens)

        score = 0.0
        for term in query_tokens:
            if term not in tf_counter:
                continue

            tf = tf_counter[term]
            idf = self._compute_idf(term)

            # BM25 公式
            numerator = tf * (self.config.k1 + 1)
            denominator = tf + self.config.k1 * (
                1 - self.config.b
                + self.config.b * doc_length / self._avg_doc_length
            )

            score += idf * numerator / denominator

        return score

    def search(
        self, query: str, top_k: int = 10
    ) -> list[tuple[MemoryChunk, float]]:
        """关键词搜索

        Returns:
            [(chunk, score), ...] 按分数降序排列
        """
        if self._total_docs == 0:
            return []

        # 查询分词
        query_tokens = self._tokenize(query)
        if not query_tokens:
            return []

        # 计算所有文档的 BM25 分数
        scores: list[tuple[str, float]] = []
        for doc_id in self._chunks:
            score = self._compute_bm25_score(query_tokens, doc_id)
            if score > 0:
                scores.append((doc_id, score))

        # 排序
        scores.sort(key=lambda x: x[1], reverse=True)

        # 返回 top_k
        results: list[tuple[MemoryChunk, float]] = []
        for doc_id, score in scores[:top_k]:
            chunk = self._chunks.get(doc_id)
            if chunk:
                # 归一化分数到 0-1 范围（近似）
                normalized_score = score / (score + 1)
                results.append((chunk, normalized_score))

        return results

    def clear(self) -> None:
        """清空索引"""
        self._chunks.clear()
        self._doc_tokens.clear()
        self._doc_lengths.clear()
        self._df.clear()
        self._total_docs = 0
        self._avg_doc_length = 0.0
        logger.info("Cleared BM25 index")

    def remove(self, ids: list[str]) -> None:
        """移除文档"""
        for doc_id in ids:
            if doc_id not in self._chunks:
                continue

            # 更新 DF
            tokens = self._doc_tokens.get(doc_id, [])
            for token in set(tokens):
                if self._df[token] > 0:
                    self._df[token] -= 1

            # 移除
            del self._chunks[doc_id]
            if doc_id in self._doc_tokens:
                del self._doc_tokens[doc_id]
            if doc_id in self._doc_lengths:
                del self._doc_lengths[doc_id]

            self._total_docs -= 1

        # 更新平均文档长度
        if self._total_docs > 0:
            self._avg_doc_length = sum(self._doc_lengths.values()) / self._total_docs
        else:
            self._avg_doc_length = 0.0

    @property
    def size(self) -> int:
        """索引的文档数量"""
        return self._total_docs

    @property
    def vocab_size(self) -> int:
        """词汇表大小"""
        return len(self._df)


# ============ 便捷函数 ============


def create_bm25_searcher(
    k1: float = 1.5,
    b: float = 0.75,
) -> JiebaBM25Searcher:
    """创建 BM25 搜索器"""
    config = BM25Config(k1=k1, b=b)
    return JiebaBM25Searcher(config)
