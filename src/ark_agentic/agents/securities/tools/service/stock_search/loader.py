"""StockLoader：加载股票列表并提供分红信息

加载优先级（股票基础数据）：
  1. 环境变量 STOCKS_CSV_PATH（显式指定）
  2. agents/securities/mock_data/stocks/a_shares_seed.csv（内置种子，随包发布）

分红信息获取策略：
  - SECURITIES_SERVICE_MOCK=true  → 从 mock_data/dividends/default.json 返回
  - 生产模式                       → 留空（由外部服务补充），可扩展为 akshare 调用
"""

from __future__ import annotations

import csv
import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from ..mock_mode import get_mock_mode_for_context
from .index import StockIndex
from .models import DividendInfo

# ── 内置种子：stock_search/ → service/ → tools/ → securities/ ──
_SEED_FILE = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "mock_data"
    / "stocks"
    / "a_shares_seed.csv"
)

# ── Mock 分红数据文件 ──────────────────────────────────────────────────────────
_MOCK_DIVIDEND_FILE = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "mock_data"
    / "dividends"
    / "default.json"
)


def _load_csv(path: Path) -> list[dict[str, Any]]:
    """从 CSV 文件加载股票基础数据"""
    rows: list[dict[str, Any]] = []
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(dict(row))
    return rows


@lru_cache(maxsize=1)
def _load_mock_dividends() -> dict[str, Any]:
    """懒加载 Mock 分红数据（进程内缓存）"""
    if _MOCK_DIVIDEND_FILE.exists():
        with open(_MOCK_DIVIDEND_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


@lru_cache(maxsize=1)
def _get_default_index() -> StockIndex:
    """懒加载默认 StockIndex（进程内缓存）"""
    csv_path = os.environ.get("STOCKS_CSV_PATH")
    if csv_path and Path(csv_path).exists():
        rows = _load_csv(Path(csv_path))
    elif _SEED_FILE.exists():
        rows = _load_csv(_SEED_FILE)
    else:
        rows = []
    return StockIndex(rows)


class StockLoader:
    """股票数据加载器

    Args:
        csv_path:    自定义 CSV 文件路径（优先于种子文件）
        mock_mode:   True 时返回内置 Mock 分红数据；False 时分红字段为 None
    """

    def __init__(
        self,
        csv_path: str | None = None,
        mock_mode: bool | None = None,
    ) -> None:
        if mock_mode is None:
            mock_mode = os.environ.get("SECURITIES_SERVICE_MOCK", "false").lower() == "true"
        self._mock_mode = mock_mode

        if csv_path:
            path = Path(csv_path)
            rows = _load_csv(path) if path.exists() else []
            self._index = StockIndex(rows)
        else:
            self._index = _get_default_index()

    @property
    def index(self) -> StockIndex:
        return self._index

    def get_dividend_info(
        self, code: str, context: dict[str, Any] | None = None
    ) -> DividendInfo | None:
        """获取分红信息

        Mock 模式返回内置数据；生产模式返回 None（由外部服务补充）。
        传入 context 时与证券工具一致：优先 user:mock_mode / mock_mode，否则环境变量；
        未传 context 时使用构造时的 mock_mode（兼容单测与脚本直接调用）。
        """
        is_mock = (
            get_mock_mode_for_context(context)
            if context is not None
            else self._mock_mode
        )
        if not is_mock:
            return None

        mock_data = _load_mock_dividends()
        raw = mock_data.get(code)
        if raw is None:
            # 有 stock 但无分红记录，返回空对象
            return DividendInfo(
                stat_date=None,
                account_type_code=None,
                market_type=None,
                stock_code=None,
                dividend_list=[],
            )

        return DividendInfo.from_api_response(raw)

    @staticmethod
    def invalidate_cache() -> None:
        """清除进程缓存（用于测试或热更新）"""
        _get_default_index.cache_clear()
        _load_mock_dividends.cache_clear()
