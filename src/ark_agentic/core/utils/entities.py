"""实体 claim 提取 — 基于 FlashText Trie 的白名单匹配。

职责：
  - EntityTrie：从 CSV 加载实体白名单，快速提取文本中的已知实体
  - EntityClaimExtractor：包装 EntityTrie 实现 ClaimExtractor 协议
"""

from __future__ import annotations

import csv
import unicodedata
from pathlib import Path
from typing import TYPE_CHECKING

from flashtext import KeywordProcessor

if TYPE_CHECKING:
    from ..validation import ExtractedClaim


class EntityTrie:
    """基于 flashtext 的实体提取器，支持 CSV 白名单加载。

    使用两个 KeywordProcessor：
    - 名称处理器（case_insensitive）：匹配归一化后的实体名称
    - 代码处理器（case_sensitive）：匹配股票代码等精确标识符
    """

    def __init__(self) -> None:
        self._processor = KeywordProcessor(case_sensitive=False)
        self._code_processor = KeywordProcessor(case_sensitive=True)

    @staticmethod
    def _normalize_name(name: str) -> str:
        """归一化实体名称：全角→半角，去除空格。"""
        result = unicodedata.normalize("NFKC", name)
        return "".join(result.split())

    def load_from_csv(
        self,
        csv_path: Path,
        *,
        name_column: str = "name",
        code_column: str = "code",
    ) -> None:
        """从 CSV 文件加载实体白名单（需包含 name 和 code 列）。"""
        with open(csv_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                raw_name = row.get(name_column, "").strip()
                code = row.get(code_column, "").strip()
                if raw_name:
                    normalized = self._normalize_name(raw_name)
                    self._processor.add_keyword(normalized, normalized)
                if code:
                    self._code_processor.add_keyword(code, code)

    def add_keywords(self, keywords: list[str]) -> None:
        """手动添加关键词。"""
        for kw in keywords:
            normalized = self._normalize_name(kw)
            self._processor.add_keyword(normalized, normalized)

    def extract(self, text: str) -> list[str]:
        """从文本中提取所有匹配的实体，返回去重有序列表。"""
        if not text:
            return []
        normalized_text = self._normalize_name(text)
        names = self._processor.extract_keywords(normalized_text)
        codes = self._code_processor.extract_keywords(text)
        seen: set[str] = set()
        result: list[str] = []
        for entity in names + codes:
            if entity not in seen:
                seen.add(entity)
                result.append(entity)
        return result


class EntityClaimExtractor:
    """包装 EntityTrie，实现 ClaimExtractor 协议。"""

    def __init__(self, trie: EntityTrie) -> None:
        self._trie = trie

    def extract_claims(self, text: str) -> list[ExtractedClaim]:
        from ..validation import ExtractedClaim

        return [
            ExtractedClaim(value=entity, type="ENTITY", normalized_values=[entity])
            for entity in self._trie.extract(text)
        ]

    def normalize_source(self, text: str, *, is_context: bool = False) -> str:
        return text
