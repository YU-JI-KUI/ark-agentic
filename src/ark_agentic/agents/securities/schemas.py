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

def get_val(d: dict, *keys):
    """获取第一个非 None 的值"""
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return None

class AccountOverviewSchema(BaseModel):
    """账户总资产标准模型
    
    支持两种数据来源：
    1. from_raw_data: 从旧格式/mock 数据创建
    2. from_api_response: 从真实 API 响应创建（通过字段提取后的数据）
    """
    
    # 基础字段
    total_assets: str = Field(..., description="总资产")
    cash_balance: str = Field(..., description="现金余额")
    stock_market_value: str = Field(..., description="股票市值")
    today_profit: str = Field(..., description="今日收益")
    total_profit: str | None = Field(None, description="累计收益")
    profit_rate: str | None = Field(None, description="收益率")
    update_time: str | None = Field(None, description="更新时间")
    
    # 新增字段（来自真实 API）
    fund_market_value: str | None = Field(None, description="基金市值")
    today_return_rate: str | None = Field(None, description="今日收益率")
    
    # 两融账户专属字段（可选）
    net_assets: str | None = Field(None, description="净资产")
    total_liabilities: str | None = Field(None, description="总负债")
    maintenance_margin_ratio: str | None = Field(None, description="维持担保比例")
    margin_ratio: str | None = Field(None, description="维持担保比率（兼容旧字段）")
    risk_level: Literal["low", "medium", "high"] | None = Field(None, description="风险等级")
    maintenance_margin: str | None = Field(None, description="维持保证金")
    available_margin: str | None = Field(None, description="可用保证金")
    
    model_config = {"populate_by_name": True}

    @classmethod
    def from_raw_data(cls, data: dict, account_type: str = "normal") -> AccountOverviewSchema:
        """从原始数据创建（支持多种字段名）
        
        用于旧格式/mock 数据的解析。
        """
        # 标准化字段名
        normalized = {
            "total_assets": get_val(data, "totalAssets", "total_asset", "total_assets"),
            "cash_balance": get_val(data, "cashBalance", "cash", "cash_balance"),
            "stock_market_value": get_val(data, "stockValue", "stock_mv", "stock_market_value"),
            "today_profit": get_val(data, "todayProfit", "profit_today", "today_profit"),
            "total_profit": get_val(data, "totalProfit", "profit_total", "total_profit"),
            "profit_rate": get_val(data, "profitRate", "profit_pct", "profit_rate"),
            "update_time": get_val(data, "updateTime", "update_time"),
            "fund_market_value": get_val(data, "fundMktVal", "fund_market_value"),
            "today_return_rate": get_val(data, "todayReturnRate", "today_return_rate"),
        }
        
        # 两融账户额外字段
        if account_type == "margin":
            normalized["net_assets"] = get_val(data, "netAssets", "net_assets", "netWorth")
            normalized["total_liabilities"] = get_val(data, "totalLiabilities", "total_liabilities")
            normalized["maintenance_margin_ratio"] = get_val(data, "maintenanceMarginRatio", "maintenance_margin_ratio", "mainRatio")
            normalized["margin_ratio"] = get_val(data, "marginRatio", "margin_pct")
            normalized["risk_level"] = get_val(data, "riskLevel", "risk")
            normalized["maintenance_margin"] = get_val(data, "maintenanceMargin")
            normalized["available_margin"] = get_val(data, "availableMargin")
        
        return cls(**normalized)
    
    @classmethod
    def from_api_response(cls, data: dict, account_type: str = "normal") -> AccountOverviewSchema:
        """从真实 API 响应创建（通过字段提取后的数据）
        
        用于从 field_extraction.extract_account_overview() 提取后的数据创建。
        字段已经是标准化的名称。
        
        Args:
            data: 从 extract_account_overview() 返回的标准化数据
            account_type: 账户类型 ("normal" 或 "margin")
        
        Returns:
            AccountOverviewSchema 实例
        """
        return cls(
            total_assets=data.get("total_assets", "0"),
            cash_balance=data.get("cash_balance", "0"),
            stock_market_value=data.get("stock_market_value", "0"),
            today_profit=data.get("today_profit", "0"),
            total_profit=data.get("total_profit"),
            profit_rate=data.get("profit_rate"),
            update_time=data.get("update_time"),
            fund_market_value=data.get("fund_market_value"),
            today_return_rate=data.get("today_return_rate"),
            # 两融账户字段
            net_assets=data.get("net_assets"),
            total_liabilities=data.get("total_liabilities"),
            maintenance_margin_ratio=data.get("maintenance_margin_ratio"),
            margin_ratio=data.get("margin_ratio"),
            risk_level=data.get("risk_level"),
            maintenance_margin=data.get("maintenance_margin"),
            available_margin=data.get("available_margin"),
        )


# ============ ETF 持仓 ============

class HoldingItemSchema(BaseModel):
    """单个持仓项"""
    
    security_code: str = Field(..., alias="securityCode", description="证券代码")
    security_name: str = Field(..., alias="securityName", description="证券名称")
    quantity: str = Field(..., alias="quantity", description="持仓数量")
    cost_price: str = Field(..., alias="costPrice", description="成本价")
    current_price: str = Field(..., alias="currentPrice", description="当前价")
    market_value: str = Field(..., alias="marketValue", description="市值")
    profit: str = Field(..., alias="profit", description="盈亏金额")
    profit_rate: str = Field(..., alias="profitRate", description="盈亏比率")
    today_profit: str | None = Field(None, alias="todayProfit", description="今日盈亏")
    
    model_config = {"populate_by_name": True}

    @field_validator("profit_rate")
    @classmethod
    def validate_profit_rate(cls, v: str) -> str:
        """验证收益率范围"""
        try:
            val = float(v)
        except (ValueError, TypeError):
            # 可能是特殊字符，视业务需求而定，这里假设必须可转数字
            raise ValueError(f"Invalid profit rate format: {v}")
            
        if not -1.0 <= val <= 10.0:  # 允许 -100% 到 1000%
            raise ValueError(f"Profit rate out of range: {val}")
        return v
    
    @classmethod
    def from_raw_data(cls, data: dict) -> HoldingItemSchema:
        """从原始数据创建"""
        return cls(
            security_code=get_val(data, "securityCode", "code"),
            security_name=get_val(data, "securityName", "name"),
            quantity=get_val(data, "quantity", "qty"),
            cost_price=get_val(data, "costPrice", "cost"),
            current_price=get_val(data, "currentPrice", "price"),
            market_value=get_val(data, "marketValue", "mv"),
            profit=get_val(data, "profit", "profitAmt"),
            profit_rate=get_val(data, "profitRate", "profitPct"),
            today_profit=get_val(data, "todayProfit"),
        )


class HoldingsSummarySchema(BaseModel):
    """持仓汇总"""
    
    total_market_value: str = Field(..., description="总市值")
    total_cost: str = Field(..., description="总成本")
    total_profit: str = Field(..., description="总盈亏")
    total_profit_rate: str = Field(..., description="总盈亏比率")
    today_profit: str = Field(..., description="今日盈亏")
    
    @classmethod
    def from_raw_data(cls, data: dict) -> HoldingsSummarySchema:
        """从原始数据创建"""
        return cls(
            total_market_value=get_val(data, "totalMarketValue", "total_mv"),
            total_cost=get_val(data, "totalCost", "total_cost"),
            total_profit=get_val(data, "totalProfit", "total_profit"),
            total_profit_rate=get_val(data, "totalProfitRate", "total_profit_pct"),
            today_profit=get_val(data, "todayProfit", "today_profit"),
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
    
    product_code: str = Field(..., alias="productCode", description="产品代码")
    product_name: str = Field(..., alias="productName", description="产品名称")
    quantity: str = Field(..., alias="quantity", description="持有份额")
    cost_price: str = Field(..., alias="costPrice", description="成本净值")
    current_value: str = Field(..., alias="currentValue", description="当前净值")
    market_value: str = Field(..., alias="marketValue", description="市值")
    profit: str = Field(..., alias="profit", description="盈亏金额")
    profit_rate: str = Field(..., alias="profitRate", description="盈亏比率")
    today_profit: str | None = Field(None, alias="todayProfit", description="今日盈亏")
    
    model_config = {"populate_by_name": True}
    
    @classmethod
    def from_raw_data(cls, data: dict) -> FundHoldingItemSchema:
        """从原始数据创建"""
        return cls(
            product_code=get_val(data, "productCode", "code"),
            product_name=get_val(data, "productName", "name"),
            quantity=get_val(data, "quantity", "qty"),
            cost_price=get_val(data, "costPrice", "cost"),
            current_value=get_val(data, "currentValue", "value"),
            market_value=get_val(data, "marketValue", "mv"),
            profit=get_val(data, "profit"),
            profit_rate=get_val(data, "profitRate", "profitPct"),
            today_profit=get_val(data, "todayProfit"),
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
    
    available_cash: str = Field(..., description="可用资金")
    frozen_cash: str = Field(..., description="冻结资金")
    total_cash: str = Field(..., description="总资金")
    update_time: str | None = Field(None, description="更新时间")
    
    @classmethod
    def from_raw_data(cls, data: dict) -> CashAssetsSchema:
        """从原始数据创建"""
        return cls(
            available_cash=get_val(data, "availableCash", "available"),
            frozen_cash=get_val(data, "frozenCash", "frozen"),
            total_cash=get_val(data, "totalCash", "total"),
            update_time=get_val(data, "updateTime", "update_time"),
        )


# ============ 具体标的详情 ============

class SecurityHoldingSchema(BaseModel):
    """标的持仓信息"""
    
    quantity: str = Field(..., alias="quantity", description="持仓数量")
    available_quantity: str = Field(..., alias="availableQuantity", description="可用数量")
    cost_price: str = Field(..., alias="costPrice", description="成本价")
    current_price: str = Field(..., alias="currentPrice", description="当前价")
    market_value: str = Field(..., alias="marketValue", description="市值")
    profit: str = Field(..., alias="profit", description="盈亏金额")
    profit_rate: str = Field(..., alias="profitRate", description="盈亏比率")
    today_profit: str = Field(..., alias="todayProfit", description="今日盈亏")
    today_profit_rate: str = Field(..., alias="todayProfitRate", description="今日盈亏比率")
    
    model_config = {"populate_by_name": True}
    
    @classmethod
    def from_raw_data(cls, data: dict) -> SecurityHoldingSchema:
        """从原始数据创建"""
        return cls(
            quantity=get_val(data, "quantity", "qty"),
            available_quantity=get_val(data, "availableQuantity", "availableQty"),
            cost_price=get_val(data, "costPrice", "cost"),
            current_price=get_val(data, "currentPrice", "price"),
            market_value=get_val(data, "marketValue", "mv"),
            profit=get_val(data, "profit", "profitAmt"),
            profit_rate=get_val(data, "profitRate", "profitPct"),
            today_profit=get_val(data, "todayProfit", "todayProfitAmt"),
            today_profit_rate=get_val(data, "todayProfitRate", "todayProfitPct"),
        )


class SecurityMarketInfoSchema(BaseModel):
    """标的行情信息"""
    
    open_price: str = Field(..., alias="openPrice", description="开盘价")
    high_price: str = Field(..., alias="highPrice", description="最高价")
    low_price: str = Field(..., alias="lowPrice", description="最低价")
    volume: str = Field(..., alias="volume", description="成交量")
    turnover: str = Field(..., alias="turnover", description="成交额")
    change_rate: str = Field(..., alias="changeRate", description="涨跌幅")
    
    model_config = {"populate_by_name": True}


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
