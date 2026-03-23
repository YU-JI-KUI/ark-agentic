"""股票信息检索服务

封装 StockLoader + MultiPathMatcher，提供进程内缓存的股票查询能力。
不依赖 HTTP / 外部 API，数据来源为本地 CSV 索引。
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

from .stock_search.loader import StockLoader
from .stock_search.matcher import MultiPathMatcher
from .stock_search.models import StockSearchResult

logger = logging.getLogger(__name__)

_DEFAULT_LOADER: StockLoader | None = None


def _get_default_loader() -> StockLoader:
    """进程内单例 Loader（首次调用时初始化）"""
    global _DEFAULT_LOADER
    if _DEFAULT_LOADER is None:
        csv_path = os.getenv("STOCKS_CSV_PATH")
        _DEFAULT_LOADER = StockLoader(csv_path=csv_path)
    return _DEFAULT_LOADER


class StockSearchService:
    """股票信息检索服务

    通过 6 位代码或名称/拼音检索 A 股基本信息及分红数据。
    复用进程内 StockLoader 单例，多次调用无重复 IO 开销。
    """

    def __init__(self, loader: StockLoader | None = None) -> None:
        self._loader = loader or _get_default_loader()
        self._matcher = MultiPathMatcher(self._loader.index)

    def search(
        self,
        query: str,
        include_dividend: bool = True,
        context: dict[str, Any] | None = None,
    ) -> StockSearchResult:
        """检索股票信息

        Args:
            query: 6 位代码或名称/拼音
            include_dividend: 是否附加分红信息

        Returns:
            StockSearchResult，confidence 为 none 时 matched=False
        """
        logger.info("stock search start query=%r", query)
        t0 = time.perf_counter()
        result = self._matcher.search(query)
        matcher_ms = (time.perf_counter() - t0) * 1000
        logger.info(
            "stock search matcher done query=%r matched=%s score=%.2f stock=%r confidence=%s matcher_ms=%.2f",
            query,
            result.matched,
            result.score,
            result.stock,
            result.confidence,
            matcher_ms,
        )
        if include_dividend and result.matched and result.stock:
            t1 = time.perf_counter()
            result.dividend_info = self._loader.get_dividend_info(
                result.stock.code, context=context
            )
            div_ms = (time.perf_counter() - t1) * 1000
            logger.info(
                "stock search dividend done code=%s dividend_ms=%.2f",
                result.stock.code,
                div_ms,
            )

        return result
