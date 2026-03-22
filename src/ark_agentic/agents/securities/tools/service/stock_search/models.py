"""股票搜索 Pydantic 数据模型"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class StockEntity(BaseModel):
    """A 股基本信息"""

    code: str = Field(..., description="6 位股票代码，如 600519")
    name: str = Field(..., description="股票名称，如 贵州茅台")
    exchange: str = Field(..., description="交易所简称：SH / SZ / BJ")
    full_code: str = Field(..., description="带交易所后缀代码，如 600519.SH")
    pinyin: str = Field(default="", description="名称全拼，用于拼音匹配")
    initials: str = Field(default="", description="名称首字母缩写，用于缩写匹配")


class DividendInfo(BaseModel):
    """分红信息"""

    dividend_per_share: str | None = Field(None, description="每股分红（元）")
    dividend_yield: str | None = Field(None, description="股息率（%）")
    ex_dividend_date: str | None = Field(None, description="除权除息日，格式 YYYY-MM-DD")
    frequency: str | None = Field(None, description="分红频率：年度 / 半年度 / 季度")
    last_year_total: str | None = Field(None, description="上年度累计分红（元/股）")


class StockSearchResult(BaseModel):
    """股票搜索结果"""

    matched: bool = Field(..., description="是否找到匹配结果")
    confidence: Literal["exact", "high", "ambiguous", "none"] = Field(
        ...,
        description=(
            "匹配置信度："
            " exact=精确匹配（score≥0.95）,"
            " high=高置信度（0.80≤score<0.95）,"
            " ambiguous=模糊匹配（0.60≤score<0.80，返回候选列表）,"
            " none=未匹配（score<0.60）"
        ),
    )
    score: float = Field(default=0.0, description="最终综合匹配分数（0.0–1.0）")
    stock: StockEntity | None = Field(None, description="匹配到的股票实体（仅 exact/high 时有值）")
    dividend_info: DividendInfo | None = Field(None, description="分红信息（需查询时返回）")
    candidates: list[dict] = Field(
        default_factory=list,
        description="候选列表（ambiguous 时返回 Top 3，每项含 code/name/exchange/score）",
    )
    raw_query: str = Field(..., description="原始查询输入")
