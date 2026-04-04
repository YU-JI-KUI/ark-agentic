r"""MultiPathMatcher：多路匹配 + 综合打分决策

匹配流水线：
  路径 A：正则 r'^\d{6}$' → 精确代码查找 → score=1.0
  路径 D：纯英文字母 → initials_map 精确首字母匹配（先于 B/C）
  路径 B：rapidfuzz.WRatio  → 名称模糊匹配
  路径 C：pypinyin 转拼音   → 拼音相似度匹配（ASR 纠错核心）

B/C 综合打分 = max(score_B, score_C)；D 命中则直接返回

决策：
  score >= 0.95 → confidence="exact"
  0.80 <= score → confidence="high"
  0.60 <= score → confidence="ambiguous"，返回 Top 3
  score < 0.60  → confidence="none"
"""

from __future__ import annotations

import logging
import re

from .index import StockIndex, _to_initials, _to_pinyin
from .models import StockEntity, StockSearchResult

_CODE_RE = re.compile(r"^\d{6}$")

_THRESHOLD_EXACT = 95.0
_THRESHOLD_HIGH = 80.0
_THRESHOLD_AMBIGUOUS = 60.0
_TOP_N = 3

logger = logging.getLogger(__name__)

def _rapidfuzz_available() -> bool:
    try:
        import rapidfuzz  # noqa: F401

        return True
    except ImportError:
        logger.warning("rapidfuzz is not installed, falling back to exact match")
        return False


def _extract_top(query: str, choices: list[str], n: int = _TOP_N) -> list[tuple[str, float, int]]:
    """使用 rapidfuzz 提取 Top-N，返回 (choice, score, idx) 列表"""
    from rapidfuzz import process as rf_process
    from rapidfuzz.fuzz import WRatio

    results = rf_process.extract(query, choices, scorer=WRatio, limit=n)
    return [(r[0], r[1], r[2]) for r in results]


def _score_to_01(score: float) -> float:
    """rapidfuzz 返回 0-100，转换为 0-1"""
    return score / 100.0


class MultiPathMatcher:
    """三路匹配器

    Args:
        index: 已构建好的 StockIndex 实例
    """

    def __init__(self, index: StockIndex) -> None:
        self._index = index
        self._has_rapidfuzz = _rapidfuzz_available()

    def search(self, query: str) -> StockSearchResult:
        """主入口：对 query 执行完整匹配流水线"""
        query = query.strip()
        if not query:
            return StockSearchResult(
                matched=False,
                confidence="none",
                score=0.0,
                raw_query=query,
                dividend_info=None,
                stock=None
            )

        # ── 路径 A：精确代码匹配 ─────────────────────────────────────
        if _CODE_RE.match(query):
            entity = self._index.find_by_code(query)
            if entity:
                return StockSearchResult(
                    matched=True,
                    confidence="exact",
                    score=1.0,
                    stock=entity,
                    raw_query=query,
                    dividend_info=None
                )

        # ── 路径 B + C：模糊匹配 ────────────────────────────────────
        if not self._has_rapidfuzz:
            # 降级：仅做精确名称查找
            entity = self._index.find_by_name(query)
            if entity:
                return StockSearchResult(
                    matched=True,
                    confidence="exact",
                    score=1.0,
                    stock=entity,
                    raw_query=query,
                    dividend_info=None
                )
            return StockSearchResult(
                matched=False, confidence="none", score=0.0, raw_query=query, stock=None, dividend_info=None
            )

        return self._fuzzy_match(query)

    def _fuzzy_match(self, query: str) -> StockSearchResult:
        # 路径 D：纯字母 ASCII → 首字母缩写精确查找（StockIndex.initials_map）
        if query.isascii() and query.isalpha():
            q = query.lower()
            initials_hits = self._index.find_by_initials(q)
            if len(initials_hits) == 1:
                return StockSearchResult(
                    matched=True,
                    confidence="exact",
                    score=1.0,
                    stock=initials_hits[0],
                    raw_query=query,
                    dividend_info=None
                )
            if len(initials_hits) > 1:
                candidates = [
                    {
                        "code": e.code,
                        "name": e.name,
                        "exchange": e.exchange,
                        "full_code": e.full_code,
                        "score": 1.0,
                    }
                    for e in initials_hits[:_TOP_N]
                ]
                return StockSearchResult(
                    matched=False,
                    confidence="ambiguous",
                    score=1.0,
                    candidates=candidates,
                    raw_query=query,
                    stock=None,
                    dividend_info=None
                )

        # 路径 B：名称模糊匹配
        name_results = _extract_top(query, self._index.all_names, _TOP_N * 2)

        # 路径 C：拼音匹配
        # 纯 ASCII 输入（如 "maotai"）直接作为拼音查询；中文先转拼音
        query_pinyin = query.lower() if query.isascii() else _to_pinyin(query)
        query_initials = query.lower() if query.isascii() else _to_initials(query)
        pinyin_results = _extract_top(query_pinyin, self._index.all_pinyins, _TOP_N * 2)

        # ── 合并、去重、取综合最高分 ──────────────────────────────────
        # key=entity_code, value=max score
        score_map: dict[str, float] = {}
        entity_map: dict[str, StockEntity] = {}

        for (choice, score, idx) in name_results:
            e = self._index.get_entity_by_name(choice)
            if e:
                current = score_map.get(e.code, 0.0)
                if score > current:
                    score_map[e.code] = score
                    entity_map[e.code] = e

        for (choice, score, idx) in pinyin_results:
            e = self._index.get_entity_by_pinyin(choice)
            if e:
                # 首字母命中时略微加分（处理如 "gzmt" → 贵州茅台）
                if query_initials and e.initials.startswith(query_initials):
                    score = min(score + 5.0, 100.0)
                current = score_map.get(e.code, 0.0)
                if score > current:
                    score_map[e.code] = score
                    entity_map[e.code] = e

        if not score_map:
            return StockSearchResult(
                matched=False, confidence="none", score=0.0, raw_query=query, stock=None, dividend_info=None
            )

        # 排序取 Top N
        sorted_items = sorted(score_map.items(), key=lambda x: x[1], reverse=True)
        best_code, best_score_100 = sorted_items[0]
        best_score = _score_to_01(best_score_100)
        best_entity = entity_map[best_code]

        # ── 决策 ────────────────────────────────────────────────────
        if best_score_100 >= _THRESHOLD_EXACT:
            return StockSearchResult(
                matched=True,
                confidence="exact",
                score=best_score,
                stock=best_entity,
                raw_query=query,
                dividend_info=None,
            )

        if best_score_100 >= _THRESHOLD_HIGH:
            return StockSearchResult(
                matched=True,
                confidence="high",
                score=best_score,
                stock=best_entity,
                raw_query=query,
                dividend_info=None
            )

        if best_score_100 >= _THRESHOLD_AMBIGUOUS:
            candidates = [
                {
                    "code": entity_map[code].code,
                    "name": entity_map[code].name,
                    "exchange": entity_map[code].exchange,
                    "full_code": entity_map[code].full_code,
                    "score": round(_score_to_01(s), 3),
                }
                for code, s in sorted_items[:_TOP_N]
            ]
            return StockSearchResult(
                matched=False,
                confidence="ambiguous",
                score=best_score,
                candidates=candidates,
                raw_query=query,
                stock=None,
                dividend_info=None
            )

        return StockSearchResult(
            matched=False, confidence="none", score=best_score, raw_query=query, stock=None, dividend_info=None
        )
