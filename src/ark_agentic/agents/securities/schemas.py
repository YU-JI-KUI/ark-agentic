"""
证券数据模型

使用 Pydantic 定义标准化数据结构，支持：
- 自动字段映射（通过 Field(alias=...)）
- 类型校验
- 数据验证
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


# ============ 账户总资产 ============

class AccountOverviewSchema(BaseModel):
    """账户总资产标准模型"""
    
    total_assets: float = Field(
        ...,
        description="总资产"
    )
    cash_balance: float = Field(
        ...,
        description="现金余额"
    )
    stock_market_value: float = Field(
        ...,
        description="股票市值"
    )
    today_profit: float = Field(
        ...,
        description="今日收益"
    )
    total_profit: float = Field(
        ...,
        description="累计收益"
    )
    profit_rate: float = Field(
        ...,
        description="收益率"
    )
    update_time: str | None = Field(
        None,
        description="更新时间"
    )
    
    # 两融账户专属字段（可选）
    margin_ratio: float | None = Field(
        None,
        description="维持担保比率"
    )
    risk_level: Literal["low", "medium", "high"] | None = Field(
        None,
        description="风险等级"
    )
    maintenance_margin: float | None = Field(
        None,
        description="维持保证金"
    )
    available_margin: float | None = Field(
        None,
        description="可用保证金"
    )
    
    class Config:
        populate_by_name = True

    @classmethod
    def from_raw_data(cls, data: dict, account_type: str = "normal") -> AccountOverviewSchema:
        """从原始数据创建（支持多种字段名）"""
        # 标准化字段名
        normalized = {
            "total_assets": data.get("totalAssets") or data.get("total_asset"),
            "cash_balance": data.get("cashBalance") or data.get("cash"),
            "stock_market_value": data.get("stockValue") or data.get("stock_mv"),
            "today_profit": data.get("todayProfit") or data.get("profit_today"),
            "total_profit": data.get("totalProfit") or data.get("profit_total"),
            "profit_rate": data.get("profitRate") or data.get("profit_pct"),
            "update_time": data.get("updateTime") or data.get("update_time"),
        }
        
        # 两融账户额外字段
        if account_type == "margin":
            normalized["margin_ratio"] = data.get("marginRatio") or data.get("margin_pct")
            normalized["risk_level"] = data.get("riskLevel") or data.get("risk")
            normalized["maintenance_margin"] = data.get("maintenanceMargin")
            normalized["available_margin"] = data.get("availableMargin")
        
        return cls(**normalized)


# ============ ETF 持仓 ============

class HoldingItemSchema(BaseModel):
    """单个持仓项"""
    
    security_code: str = Field(..., description="证券代码")
    security_name: str = Field(..., description="证券名称")
    quantity: int = Field(..., description="持仓数量")
    cost_price: float = Field(..., description="成本价")
    current_price: float = Field(..., description="当前价")
    market_value: float = Field(..., description="市值")
    profit: float = Field(..., description="盈亏金额")
    profit_rate: float = Field(..., description="盈亏比率")
    today_profit: float | None = Field(None, description="今日盈亏")
    
    @field_validator("profit_rate")
    @classmethod
    def validate_profit_rate(cls, v: float) -> float:
        """验证收益率范围"""
        if not -1.0 <= v <= 10.0:  # 允许 -100% 到 1000%
            raise ValueError(f"Profit rate out of range: {v}")
        return v
    
    @classmethod
    def from_raw_data(cls, data: dict) -> HoldingItemSchema:
        """从原始数据创建"""
        return cls(
            security_code=data.get("securityCode") or data.get("code"),
            security_name=data.get("securityName") or data.get("name"),
            quantity=data.get("quantity") or data.get("qty"),
            cost_price=data.get("costPrice") or data.get("cost"),
            current_price=data.get("currentPrice") or data.get("price"),
            market_value=data.get("marketValue") or data.get("mv"),
            profit=data.get("profit") or data.get("profitAmt"),
            profit_rate=data.get("profitRate") or data.get("profitPct"),
            today_profit=data.get("todayProfit"),
        )


class HoldingsSummarySchema(BaseModel):
    """持仓汇总"""
    
    total_market_value: float = Field(..., description="总市值")
    total_cost: float = Field(..., description="总成本")
    total_profit: float = Field(..., description="总盈亏")
    total_profit_rate: float = Field(..., description="总盈亏比率")
    today_profit: float = Field(..., description="今日盈亏")
    
    @classmethod
    def from_raw_data(cls, data: dict) -> HoldingsSummarySchema:
        """从原始数据创建"""
        return cls(
            total_market_value=data.get("totalMarketValue") or data.get("total_mv"),
            total_cost=data.get("totalCost") or data.get("total_cost"),
            total_profit=data.get("totalProfit") or data.get("total_profit"),
            total_profit_rate=data.get("totalProfitRate") or data.get("total_profit_pct"),
            today_profit=data.get("todayProfit") or data.get("today_profit"),
        )


class ETFHoldingsSchema(BaseModel):
    """ETF 持仓完整模型"""
    
    holdings: list[HoldingItemSchema]
    summary: HoldingsSummarySchema
    
    @classmethod
    def from_raw_data(cls, data: dict) -> ETFHoldingsSchema:
        """从原始数据创建"""
        holdings_raw = data.get("holdings", [])
        summary_raw = data.get("summary", {})
        
        return cls(
            holdings=[HoldingItemSchema.from_raw_data(h) for h in holdings_raw],
            summary=HoldingsSummarySchema.from_raw_data(summary_raw),
        )


# ============ 港股通持仓 ============

class HKSCHoldingsSchema(BaseModel):
    """港股通持仓（复用 ETF 结构）"""
    
    holdings: list[HoldingItemSchema]
    summary: HoldingsSummarySchema
    
    @classmethod
    def from_raw_data(cls, data: dict) -> HKSCHoldingsSchema:
        """从原始数据创建"""
        holdings_raw = data.get("holdings", [])
        summary_raw = data.get("summary", {})
        
        return cls(
            holdings=[HoldingItemSchema.from_raw_data(h) for h in holdings_raw],
            summary=HoldingsSummarySchema.from_raw_data(summary_raw),
        )


# ============ 基金理财 ============

class FundHoldingItemSchema(BaseModel):
    """基金持仓项"""
    
    product_code: str = Field(..., description="产品代码")
    product_name: str = Field(..., description="产品名称")
    quantity: int = Field(..., description="持有份额")
    cost_price: float = Field(..., description="成本净值")
    current_value: float = Field(..., description="当前净值")
    market_value: float = Field(..., description="市值")
    profit: float = Field(..., description="盈亏金额")
    profit_rate: float = Field(..., description="盈亏比率")
    today_profit: float | None = Field(None, description="今日盈亏")
    
    @classmethod
    def from_raw_data(cls, data: dict) -> FundHoldingItemSchema:
        """从原始数据创建"""
        return cls(
            product_code=data.get("productCode") or data.get("code"),
            product_name=data.get("productName") or data.get("name"),
            quantity=data.get("quantity") or data.get("qty"),
            cost_price=data.get("costPrice") or data.get("cost"),
            current_value=data.get("currentValue") or data.get("value"),
            market_value=data.get("marketValue") or data.get("mv"),
            profit=data.get("profit"),
            profit_rate=data.get("profitRate") or data.get("profitPct"),
            today_profit=data.get("todayProfit"),
        )


class FundHoldingsSchema(BaseModel):
    """基金理财持仓"""
    
    holdings: list[FundHoldingItemSchema]
    summary: HoldingsSummarySchema
    
    @classmethod
    def from_raw_data(cls, data: dict) -> FundHoldingsSchema:
        """从原始数据创建"""
        holdings_raw = data.get("holdings", [])
        summary_raw = data.get("summary", {})
        
        return cls(
            holdings=[FundHoldingItemSchema.from_raw_data(h) for h in holdings_raw],
            summary=HoldingsSummarySchema.from_raw_data(summary_raw),
        )


# ============ 现金资产 ============

class CashAssetsSchema(BaseModel):
    """现金资产"""
    
    available_cash: float = Field(..., description="可用资金")
    frozen_cash: float = Field(..., description="冻结资金")
    total_cash: float = Field(..., description="总资金")
    update_time: str | None = Field(None, description="更新时间")
    
    @classmethod
    def from_raw_data(cls, data: dict) -> CashAssetsSchema:
        """从原始数据创建"""
        return cls(
            available_cash=data.get("availableCash") or data.get("available"),
            frozen_cash=data.get("frozenCash") or data.get("frozen"),
            total_cash=data.get("totalCash") or data.get("total"),
            update_time=data.get("updateTime") or data.get("update_time"),
        )


# ============ 具体标的详情 ============

class SecurityHoldingSchema(BaseModel):
    """标的持仓信息"""
    
    quantity: int = Field(..., description="持仓数量")
    available_quantity: int = Field(..., description="可用数量")
    cost_price: float = Field(..., description="成本价")
    current_price: float = Field(..., description="当前价")
    market_value: float = Field(..., description="市值")
    profit: float = Field(..., description="盈亏金额")
    profit_rate: float = Field(..., description="盈亏比率")
    today_profit: float = Field(..., description="今日盈亏")
    today_profit_rate: float = Field(..., description="今日盈亏比率")


class SecurityMarketInfoSchema(BaseModel):
    """标的行情信息"""
    
    open_price: float = Field(..., description="开盘价")
    high_price: float = Field(..., description="最高价")
    low_price: float = Field(..., description="最低价")
    volume: int = Field(..., description="成交量")
    turnover: float = Field(..., description="成交额")
    change_rate: float = Field(..., description="涨跌幅")


class SecurityDetailSchema(BaseModel):
    """具体标的详情"""
    
    security_code: str = Field(..., description="证券代码")
    security_name: str = Field(..., description="证券名称")
    security_type: str = Field(..., description="证券类型")
    market: str = Field(..., description="市场")
    holding: SecurityHoldingSchema = Field(..., description="持仓信息")
    market_info: SecurityMarketInfoSchema = Field(..., description="行情信息")
    
    @classmethod
    def from_raw_data(cls, data: dict) -> SecurityDetailSchema:
        """从原始数据创建"""
        holding_raw = data.get("holding", {})
        market_info_raw = data.get("marketInfo", {})
        
        return cls(
            security_code=data.get("securityCode") or data.get("code"),
            security_name=data.get("securityName") or data.get("name"),
            security_type=data.get("securityType") or data.get("type"),
            market=data.get("market"),
            holding=SecurityHoldingSchema(**holding_raw),
            market_info=SecurityMarketInfoSchema(**market_info_raw),
        )
