"""股票搜索 Pydantic 数据模型"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# ── 分配类型映射 ──────────────────────────────────────────────────────────────
ASSIGN_TYPE_MAP: dict[str, str] = {
    "DAT01": "第1季分红",
    "DAT02": "第2季分红",
    "DAT03": "第3季分红",
    "DAT04": "第4季分红",
    "DAT05": "中期分红",
    "DAT06": "年度分红",
    "DAT07": "其他分红",
    "DAT08": "特别分红",
    "DAT09": "重整计划",
}

# ── 分红方案类型映射 ──────────────────────────────────────────────────────────
STK_DIV_TYPE_MAP: dict[str, str] = {
    "CASH": "现金分红",
    "SENDING_SHARES": "现金分红",
    "CASH_CAPITAL_INCREASE": "现金分红+转赠",
    "CASH_SENDING_SHARES": "现金分红+送股",
    "STOCK_DIVIDEND": "送股+转赠",
    "ALL": "现金分红+股票分红",
    "NONE": "不分配",
}


def _fmt_date(raw: str | None) -> str | None:
    """将 YYYYMMDD 格式转为 YYYY-MM-DD，无法解析时原样返回"""
    if raw and len(raw) == 8 and raw.isdigit():
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"
    return raw


class DividendItem(BaseModel):
    """单条分红记录"""

    year: str = Field(..., description="分红年份，如 '2024'")
    assign_type_code: str = Field(..., description="分配期类型代码，如 'DAT06'")
    assign_type_description: str = Field(..., description="分配期类型描述，如 '年度分红'")
    arrival_date: str | None = Field(None, description="分红到账日期，格式 YYYY-MM-DD")
    stk_div_type_code: str = Field(..., description="分红方案类型代码，如 'SENDING_SHARES'")
    stk_div_type_description: str = Field(..., description="分红方案类型描述，如 '现金分红'")
    plan: str | None = Field(None, description="分红方案，如 '10派0.21送2转2'")
    plan_info: str | None = Field(None, description="分红方案说明（含税），如 '10派0.21(含税)'")
    cash_amount: str | None = Field(None, description="每千股现金分红金额（元）")
    stock_shares: int | None = Field(None, description="每千股送股数量")
    stock_name: str | None = Field(None, description="股票名称")

    @classmethod
    def from_raw(cls, d: dict) -> DividendItem:
        assign_code = d.get("assignType", "")
        stk_code = d.get("stkDivType", "")
        return cls(
            year=d.get("year", ""),
            assign_type_code=assign_code,
            assign_type_description=ASSIGN_TYPE_MAP.get(assign_code) or assign_code,
            arrival_date=_fmt_date(d.get("arrivalDate")),
            stk_div_type_code=stk_code,
            stk_div_type_description=STK_DIV_TYPE_MAP.get(stk_code) or stk_code,
            plan=d.get("plan"),
            plan_info=d.get("planInfo"),
            cash_amount=d.get("cash"),
            stock_shares=d.get("stock"),
            stock_name=d.get("stockName"),
        )


class DividendInfo(BaseModel):
    """分红信息（来自真实 API 响应）"""

    stat_date: str | None = Field(None, description="统计日期，格式 YYYY-MM-DD")
    account_type_code: str | None = Field(None, description="账户类型代码，如 '1'")
    market_type: str | None = Field(None, description="市场代码：SH=上海，SZ=深圳，BJ=北京")
    stock_code: str | None = Field(None, description="6 位股票代码")
    dividend_list: list[DividendItem] = Field(default_factory=list, description="分红记录列表")

    @classmethod
    def from_api_response(cls, raw: dict) -> DividendInfo:
        """从完整 API 响应解析 DividendInfo

        Args:
            raw: API 响应顶层 dict，含 results.dividendList / results.requestBody
        """
        results = raw.get("results", {})
        request_body = results.get("requestBody", {})
        dividend_list_raw: list[dict] = results.get("dividendList", [])
        return cls(
            stat_date=_fmt_date(results.get("statDate")),
            account_type_code=results.get("accountType"),
            market_type=request_body.get("marketType"),
            stock_code=request_body.get("stockCode"),
            dividend_list=[DividendItem.from_raw(d) for d in dividend_list_raw],
        )


class StockEntity(BaseModel):
    """A 股基本信息"""

    code: str = Field(..., description="6 位股票代码，如 600519")
    name: str = Field(..., description="股票名称，如 贵州茅台")
    exchange: str = Field(..., description="交易所简称：SH / SZ / BJ")
    full_code: str = Field(..., description="带交易所后缀代码，如 600519.SH")
    pinyin: str = Field(default="", description="名称全拼，用于拼音匹配")
    initials: str = Field(default="", description="名称首字母缩写，用于缩写匹配")


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
