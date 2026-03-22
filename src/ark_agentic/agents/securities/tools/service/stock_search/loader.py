"""StockLoader：加载股票列表并提供分红信息

加载优先级（股票基础数据）：
  1. 外部 CSV 路径（可配置）
  2. 项目 data/stocks/a_shares_seed.csv（内置种子）

分红信息获取策略：
  - SECURITIES_SERVICE_MOCK=true  → 从内置 Mock 字典返回
  - 生产模式                       → 留空（由外部服务补充），可扩展为 akshare 调用
"""

from __future__ import annotations

import csv
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from .index import StockIndex
from .models import DividendInfo

# ── 内置种子文件路径 ──────────────────────────────────────────────
_SEED_FILE = Path(__file__).parent.parent.parent.parent.parent.parent.parent.parent / "data" / "stocks" / "a_shares_seed.csv"

# ── Mock 分红数据（部分典型高股息股票） ────────────────────────────
_MOCK_DIVIDEND: dict[str, dict[str, str]] = {
    "600519": {"dividend_per_share": "19.11", "dividend_yield": "1.2%", "ex_dividend_date": "2024-07-16", "frequency": "年度", "last_year_total": "19.11"},
    "601398": {"dividend_per_share": "0.31", "dividend_yield": "6.8%", "ex_dividend_date": "2024-06-20", "frequency": "年度", "last_year_total": "0.31"},
    "601988": {"dividend_per_share": "0.21", "dividend_yield": "5.5%", "ex_dividend_date": "2024-07-01", "frequency": "年度", "last_year_total": "0.21"},
    "600036": {"dividend_per_share": "1.59", "dividend_yield": "4.8%", "ex_dividend_date": "2024-06-18", "frequency": "年度", "last_year_total": "1.59"},
    "601288": {"dividend_per_share": "0.23", "dividend_yield": "5.2%", "ex_dividend_date": "2024-07-05", "frequency": "年度", "last_year_total": "0.23"},
    "600028": {"dividend_per_share": "0.35", "dividend_yield": "3.9%", "ex_dividend_date": "2024-06-28", "frequency": "年度", "last_year_total": "0.35"},
    "601857": {"dividend_per_share": "0.41", "dividend_yield": "4.5%", "ex_dividend_date": "2024-07-10", "frequency": "年度", "last_year_total": "0.41"},
    "600900": {"dividend_per_share": "0.91", "dividend_yield": "3.1%", "ex_dividend_date": "2024-06-25", "frequency": "年度", "last_year_total": "0.91"},
    "600887": {"dividend_per_share": "1.22", "dividend_yield": "3.3%", "ex_dividend_date": "2024-06-14", "frequency": "年度", "last_year_total": "1.22"},
    "000858": {"dividend_per_share": "19.30", "dividend_yield": "3.7%", "ex_dividend_date": "2024-06-24", "frequency": "年度", "last_year_total": "19.30"},
    "000568": {"dividend_per_share": "6.60", "dividend_yield": "2.9%", "ex_dividend_date": "2024-07-03", "frequency": "年度", "last_year_total": "6.60"},
    "600809": {"dividend_per_share": "4.80", "dividend_yield": "2.5%", "ex_dividend_date": "2024-06-19", "frequency": "年度", "last_year_total": "4.80"},
    "000001": {"dividend_per_share": "0.79", "dividend_yield": "4.1%", "ex_dividend_date": "2024-07-08", "frequency": "年度", "last_year_total": "0.79"},
    "000333": {"dividend_per_share": "1.57", "dividend_yield": "5.3%", "ex_dividend_date": "2024-06-17", "frequency": "年度", "last_year_total": "1.57"},
    "000651": {"dividend_per_share": "2.00", "dividend_yield": "5.9%", "ex_dividend_date": "2024-06-21", "frequency": "年度", "last_year_total": "2.00"},
    "300750": {"dividend_per_share": "2.92", "dividend_yield": "1.4%", "ex_dividend_date": "2024-06-26", "frequency": "年度", "last_year_total": "2.92"},
    "600585": {"dividend_per_share": "1.58", "dividend_yield": "4.2%", "ex_dividend_date": "2024-07-02", "frequency": "年度", "last_year_total": "1.58"},
    "601166": {"dividend_per_share": "0.99", "dividend_yield": "6.2%", "ex_dividend_date": "2024-06-13", "frequency": "年度", "last_year_total": "0.99"},
    "601318": {"dividend_per_share": "2.44", "dividend_yield": "5.1%", "ex_dividend_date": "2024-07-12", "frequency": "年度", "last_year_total": "2.44"},
    "600309": {"dividend_per_share": "4.57", "dividend_yield": "3.6%", "ex_dividend_date": "2024-06-27", "frequency": "年度", "last_year_total": "4.57"},
}


def _load_csv(path: Path) -> list[dict[str, Any]]:
    """从 CSV 文件加载股票基础数据"""
    rows: list[dict[str, Any]] = []
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(dict(row))
    return rows


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

    def get_dividend_info(self, code: str) -> DividendInfo | None:
        """获取分红信息

        Mock 模式返回内置数据；生产模式返回 None（由外部服务补充）。
        """
        if not self._mock_mode:
            return None

        raw = _MOCK_DIVIDEND.get(code)
        if raw is None:
            return DividendInfo()  # 有 stock 但无分红记录，返回空对象

        return DividendInfo(
            dividend_per_share=raw.get("dividend_per_share"),
            dividend_yield=raw.get("dividend_yield"),
            ex_dividend_date=raw.get("ex_dividend_date"),
            frequency=raw.get("frequency"),
            last_year_total=raw.get("last_year_total"),
        )

    @staticmethod
    def invalidate_cache() -> None:
        """清除进程缓存（用于测试或热更新）"""
        _get_default_index.cache_clear()
