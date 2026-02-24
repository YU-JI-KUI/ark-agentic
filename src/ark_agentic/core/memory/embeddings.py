"""
BGE Embedding 封装

使用 sentence-transformers 加载 BGE 模型生成向量。
支持的模型:
- BAAI/bge-base-zh-v1.5 (512 max tokens, 768 dims) - 推荐，平衡效果和速度
- BAAI/bge-large-zh-v1.5 (512 max tokens, 1024 dims) - 效果最好但较慢

可通过环境变量 EMBEDDING_MODEL_PATH 指定本地模型路径。
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)

# 默认模型
DEFAULT_BGE_MODEL = "BAAI/bge-base-zh-v1.5"

# 模型维度映射
BGE_MODEL_DIMS = {
    "BAAI/bge-base-zh-v1.5": 768,
    "BAAI/bge-large-zh-v1.5": 1024,
}


@dataclass
class BGEConfig:
    """BGE 配置

    model_name 优先级：
    1. 构造时显式传入的 model_name
    2. 环境变量 EMBEDDING_MODEL_PATH（本地路径或 HuggingFace ID）
    3. DEFAULT_BGE_MODEL
    """

    model_name: str = ""
    device: str = "cpu"  # "cpu", "cuda", "mps"
    normalize_embeddings: bool = True
    max_length: int = 512
    batch_size: int = 32
    show_progress: bool = False

    # 查询前缀（BGE 推荐对查询加前缀）
    query_instruction: str = "为这个句子生成表示以用于检索相关文章："

    def __post_init__(self) -> None:
        if not self.model_name:
            self.model_name = os.getenv("EMBEDDING_MODEL_PATH", DEFAULT_BGE_MODEL)


class BGEEmbedding:
    """BGE Embedding 提供者

    使用 sentence-transformers 库加载 BGE 模型。
    """

    def __init__(self, config: BGEConfig | None = None) -> None:
        self.config = config or BGEConfig()
        self._model: Optional[Any] = None  # SentenceTransformer model, kept as Any due to optional dependency
        self._dimensions: int = 0

    @property
    def model_name(self) -> str:
        return self.config.model_name

    @property
    def dimensions(self) -> int:
        if self._dimensions == 0:
            # 尝试从映射获取
            self._dimensions = BGE_MODEL_DIMS.get(self.config.model_name, 0)
            if self._dimensions == 0 and self._model is not None:
                # 从模型获取
                self._dimensions = self._model.get_sentence_embedding_dimension()
        return self._dimensions

    def _ensure_model(self) -> Any:
        """确保模型已加载"""
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError:
                raise ImportError(
                    "sentence-transformers is required. "
                    "Install with: pip install sentence-transformers"
                )

            logger.info(f"Loading BGE model: {self.config.model_name}")
            self._model = SentenceTransformer(
                self.config.model_name,
                device=self.config.device,
            )
            self._dimensions = self._model.get_sentence_embedding_dimension()
            logger.info(
                f"BGE model loaded: {self.config.model_name}, "
                f"dims={self._dimensions}, device={self.config.device}"
            )

        return self._model

    def _normalize(self, embedding: list[float]) -> list[float]:
        """L2 归一化"""
        import math

        magnitude = math.sqrt(sum(x * x for x in embedding))
        if magnitude < 1e-10:
            return embedding
        return [x / magnitude for x in embedding]

    async def embed_query(self, text: str) -> list[float]:
        """嵌入查询文本

        对查询文本添加指令前缀以提升检索效果。
        """
        model = self._ensure_model()

        # 添加查询指令前缀
        if self.config.query_instruction:
            text = self.config.query_instruction + text

        # 在线程池中运行（避免阻塞事件循环）
        loop = asyncio.get_event_loop()
        embedding = await loop.run_in_executor(
            None,
            lambda: model.encode(
                text,
                normalize_embeddings=self.config.normalize_embeddings,
                show_progress_bar=False,
            ).tolist(),
        )

        return embedding

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """批量嵌入文本

        用于索引文档，不添加查询指令前缀。
        """
        if not texts:
            return []

        model = self._ensure_model()

        # 在线程池中运行
        loop = asyncio.get_event_loop()
        embeddings = await loop.run_in_executor(
            None,
            lambda: model.encode(
                texts,
                normalize_embeddings=self.config.normalize_embeddings,
                batch_size=self.config.batch_size,
                show_progress_bar=self.config.show_progress,
            ).tolist(),
        )

        return embeddings

    def embed_query_sync(self, text: str) -> list[float]:
        """同步版本：嵌入查询文本"""
        model = self._ensure_model()

        if self.config.query_instruction:
            text = self.config.query_instruction + text

        embedding = model.encode(
            text,
            normalize_embeddings=self.config.normalize_embeddings,
            show_progress_bar=False,
        ).tolist()

        return embedding

    def embed_batch_sync(self, texts: list[str]) -> list[list[float]]:
        """同步版本：批量嵌入文本"""
        if not texts:
            return []

        model = self._ensure_model()

        embeddings = model.encode(
            texts,
            normalize_embeddings=self.config.normalize_embeddings,
            batch_size=self.config.batch_size,
            show_progress_bar=self.config.show_progress,
        ).tolist()

        return embeddings


# ============ 便捷函数 ============


def create_bge_embedding(
    model_name: str = DEFAULT_BGE_MODEL,
    device: str = "cpu",
) -> BGEEmbedding:
    """创建 BGE Embedding 实例"""
    config = BGEConfig(model_name=model_name, device=device)
    return BGEEmbedding(config)


def get_available_devices() -> list[str]:
    """获取可用的计算设备"""
    devices = ["cpu"]

    try:
        import torch

        if torch.cuda.is_available():
            devices.append("cuda")
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            devices.append("mps")
    except ImportError:
        pass

    return devices


def get_recommended_model() -> str:
    """获取推荐的模型"""
    return DEFAULT_BGE_MODEL
