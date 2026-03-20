"""
证券数据模型

使用 Pydantic 定义标准化数据结构，支持：
- 自动字段映射
- 类型校验
- 数据验证
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


# ============ 账户总资产 ============

class RzrqAssetsInfoSchema(BaseModel):
    """两融资产信息（原始 API 结构）"""

    netWorth: str | None = Field(None, description="净资产")
    totalLiabilities: str | None = Field(None, description="总负债")
    mainRatio: str | None = Field(None, description="维持担保比例")

    model_config = {"populate_by_name": True, "extra": "allow"}


class AccountOverviewSchema(BaseModel):
    """账户总资产标准模型

    对齐 queryAccountAssetResultTpl 数据格式：
    extract_account_overview() → template_renderer → 此 Schema
    """

    # 顶层元数据
    title: str = Field(default="", description="卡片标题（含脱敏账号）")
    account_type: str = Field(default="normal", description="账户类型 normal|margin")

    # 嵌套资产数据（保留原始 API 字段名）
    total_assets: str = Field(..., alias="totalAssetVal", description="总资产")
    positions: str | None = Field(None, description="仓位比例")
    prudent_positions: str | None = Field(None, alias="prudentPositions", description="稳健仓位")

    # 子对象
    mkt_assets_info: dict[str, Any] = Field(default_factory=dict, alias="mktAssetsInfo")
    fund_mkt_assets_info: dict[str, Any] = Field(default_factory=dict, alias="fundMktAssetsInfo")
    cash_gain_assets_info: dict[str, Any] = Field(default_factory=dict, alias="cashGainAssetsInfo")
    rzrq_assets_info: RzrqAssetsInfoSchema | None = Field(None, alias="rzrqAssetsInfo")

    model_config = {"populate_by_name": True, "extra": "allow"}

    @classmethod
    def from_template_data(cls, data: dict) -> AccountOverviewSchema:
        """从 template_renderer.render_account_overview_card() 的 data 字段创建"""
        ad = data.get("assetData", {})
        rzrq_raw = ad.get("rzrqAssetsInfo")
        return cls(
            title=data.get("title", ""),
            account_type=data.get("account_type", "normal"),
            totalAssetVal=ad.get("totalAssetVal", "0.00"),
            positions=ad.get("positions"),
            prudentPositions=ad.get("prudentPositions"),
            mktAssetsInfo=ad.get("mktAssetsInfo", {}),
            fundMktAssetsInfo=ad.get("fundMktAssetsInfo", {}),
            cashGainAssetsInfo=ad.get("cashGainAssetsInfo", {}),
            rzrqAssetsInfo=RzrqAssetsInfoSchema(**rzrq_raw) if rzrq_raw else None,
        )


# ============ ETF 持仓 ============

class ETFHoldingItemSchema(BaseModel):
    """ETF 持仓项
    
    从 field_extraction.extract_etf_holdings() 提取后的数据创建。
    """
    
    code: str = Field(..., description="证券代码")
    name: str = Field(..., description="证券名称")
    hold_cnt: str = Field(..., description="持仓数量")
    market_value: str = Field(..., description="市值")
    day_profit: str | None = Field(None, description="今日收益")
    day_profit_rate: str | None = Field(None, description="今日收益率")
    price: str | None = Field(None, description="当前价格")
    cost_price: str | None = Field(None, description="成本价")
    market_type: str | None = Field(None, description="市场类型")
    hold_position_profit: str | None = Field(None, description="持仓盈亏")
    hold_position_profit_rate: str | None = Field(None, description="持仓盈亏率")
    
    model_config = {"populate_by_name": True}
    
    @classmethod
    def from_api_response(cls, data: dict) -> ETFHoldingItemSchema:
        """从字段提取后的数据创建"""
        return cls(
            code=data.get("code", ""),
            name=data.get("name", ""),
            hold_cnt=data.get("hold_cnt", "0"),
            market_value=data.get("market_value", "0"),
            day_profit=data.get("day_profit"),
            day_profit_rate=data.get("day_profit_rate"),
            price=data.get("price"),
            cost_price=data.get("cost_price"),
            market_type=data.get("market_type"),
            hold_position_profit=data.get("hold_position_profit"),
            hold_position_profit_rate=data.get("hold_position_profit_rate"),
        )


class ETFHoldingsSchema(BaseModel):
    """ETF 持仓完整模型
    
    从 field_extraction.extract_etf_holdings() 提取后的数据创建。
    """
    
    total: int = Field(default=0, description="持仓数量")
    total_market_value: str = Field(default="0", description="总市值")
    total_profit: str = Field(default="0", description="今日总收益")
    total_profit_rate: str | None = Field(None, description="今日收益率")
    account_type: int | None = Field(None, description="账户类型")
    stock_list: list[ETFHoldingItemSchema] = Field(default_factory=list, description="持仓列表")
    
    model_config = {"populate_by_name": True}
    
    @classmethod
    def from_api_response(cls, data: dict) -> ETFHoldingsSchema:
        """从 API 响应创建（通过字段提取后的数据）
        
        用于从 field_extraction.extract_etf_holdings() 提取后的数据创建。
        字段已经是标准化的名称。
        
        Args:
            data: 从 extract_etf_holdings() 返回的标准化数据
        
        Returns:
            ETFHoldingsSchema 实例
        """
        stock_list_raw = data.get("stock_list", [])
        return cls(
            total=data.get("total", 0),
            total_market_value=data.get("total_market_value", "0"),
            total_profit=data.get("total_profit", "0"),
            total_profit_rate=data.get("total_profit_rate"),
            account_type=data.get("account_type"),
            stock_list=[ETFHoldingItemSchema.from_api_response(s) for s in stock_list_raw],
        )


# ============ 港股通持仓 ============

class HKSCHoldingItemSchema(BaseModel):
    """港股通持仓项
    
    从 field_extraction.extract_hksc_holdings() 提取后的数据创建。
    """
    
    code: str = Field(..., description="证券代码")
    name: str = Field(..., description="证券名称")
    hold_cnt: str = Field(..., description="持仓数量")
    share_bln: str | None = Field(None, description="可用份额")
    market_value: str | None = Field(None, description="市值")
    day_profit: str | None = Field(None, description="今日收益")
    day_profit_rate: str | None = Field(None, description="今日收益率")
    price: str | None = Field(None, description="当前价格")
    cost_price: str | None = Field(None, description="成本价")
    market_type: str | None = Field(None, description="市场类型")
    hold_position_profit: str | None = Field(None, description="持仓盈亏")
    hold_position_profit_rate: str | None = Field(None, description="持仓盈亏率")
    position: str | None = Field(None, description="持仓位置")
    secu_acc: str | None = Field(None, description="证券账户")
    
    model_config = {"populate_by_name": True}
    
    @classmethod
    def from_api_response(cls, data: dict) -> HKSCHoldingItemSchema:
        """从字段提取后的数据创建"""
        return cls(
            code=data.get("code", ""),
            name=data.get("name", ""),
            hold_cnt=data.get("hold_cnt", "0"),
            share_bln=data.get("share_bln"),
            market_value=data.get("market_value"),
            day_profit=data.get("day_profit"),
            day_profit_rate=data.get("day_profit_rate"),
            price=data.get("price"),
            cost_price=data.get("cost_price"),
            market_type=data.get("market_type"),
            hold_position_profit=data.get("hold_position_profit"),
            hold_position_profit_rate=data.get("hold_position_profit_rate"),
            position=data.get("position"),
            secu_acc=data.get("secu_acc"),
        )


class HKSCPreFrozenItemSchema(BaseModel):
    """港股通预冻结项"""
    
    code: str = Field(..., description="证券代码")
    name: str = Field(..., description="证券名称")
    pre_frozen_asset: str | None = Field(None, description="预冻结资产")
    
    model_config = {"populate_by_name": True}


class HKSCHoldingsSchema(BaseModel):
    """港股通持仓完整模型
    
    从 field_extraction.extract_hksc_holdings() 提取后的数据创建。
    """
    
    # 汇总字段
    hold_market_value: str = Field(default="0", description="持仓市值")
    hold_position_profit: str | None = Field(None, description="持仓盈亏")
    day_total_profit: str = Field(default="0", description="今日总收益")
    day_total_profit_rate: str | None = Field(None, description="今日收益率")
    total_hksc_share: str | None = Field(None, description="港股通总额度")
    available_hksc_share: str | None = Field(None, description="港股通可用额度")
    limit_hksc_share: str | None = Field(None, description="港股通限额")
    pre_frozen_asset: str | None = Field(None, description="预冻结资产")
    progress: int | None = Field(None, description="进度")
    stock_list: list[HKSCHoldingItemSchema] = Field(default_factory=list, description="持仓列表")
    pre_frozen_list: list[HKSCPreFrozenItemSchema] | None = Field(None, description="预冻结列表")
    
    model_config = {"populate_by_name": True}
    
    @classmethod
    def from_api_response(cls, data: dict) -> HKSCHoldingsSchema:
        """从 API 响应创建（通过字段提取后的数据）
        
        用于从 field_extraction.extract_hksc_holdings() 提取后的数据创建。
        字段已经是标准化的名称。
        
        Args:
            data: 从 extract_hksc_holdings() 返回的标准化数据
        
        Returns:
            HKSCHoldingsSchema 实例
        """
        stock_list_raw = data.get("stock_list", [])
        pre_frozen_raw = data.get("pre_frozen_list", [])
        
        return cls(
            hold_market_value=data.get("hold_market_value", "0"),
            hold_position_profit=data.get("hold_position_profit"),
            day_total_profit=data.get("day_total_profit", "0"),
            day_total_profit_rate=data.get("day_total_profit_rate"),
            total_hksc_share=data.get("total_hksc_share"),
            available_hksc_share=data.get("available_hksc_share"),
            limit_hksc_share=data.get("limit_hksc_share"),
            pre_frozen_asset=data.get("pre_frozen_asset"),
            progress=data.get("progress"),
            stock_list=[HKSCHoldingItemSchema.from_api_response(s) for s in stock_list_raw],
            pre_frozen_list=[HKSCPreFrozenItemSchema(**p) for p in pre_frozen_raw] if pre_frozen_raw else None,
        )


# ============ 基金理财 ============

def get_val(d: dict, *keys):
    """获取第一个非 None 的值"""
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return None


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
    """现金资产标准模型
    
    从 field_extraction.extract_cash_assets() 提取后的数据创建。
    """
    
    # 基础字段
    cash_balance: str = Field(..., description="现金总额")
    cash_available: str = Field(..., description="可用资金")
    draw_balance: str | None = Field(None, description="可取资金")
    today_profit: str | None = Field(None, description="今日收益")
    
    # 扩展字段
    account_type: str | None = Field(None, description="账户类型")
    accu_profit: str | None = Field(None, description="累计收益")
    fund_name: str | None = Field(None, description="理财产品名称")
    fund_code: str | None = Field(None, description="理财产品代码")
    frozen_funds_total: str | None = Field(None, description="冻结资金总额")
    frozen_funds_detail: list[dict] | None = Field(None, description="冻结资金明细")
    in_transit_asset_total: str | None = Field(None, description="在途资产总额")
    in_transit_asset_detail: Any | None = Field(None, description="在途资产明细")
    
    model_config = {"populate_by_name": True}
    
    @classmethod
    def from_api_response(cls, data: dict) -> CashAssetsSchema:
        """从 API 响应创建（通过字段提取后的数据）
        
        用于从 field_extraction.extract_cash_assets() 提取后的数据创建。
        字段已经是标准化的名称。
        
        Args:
            data: 从 extract_cash_assets() 返回的标准化数据
        
        Returns:
            CashAssetsSchema 实例
        """
        return cls(
            cash_balance=data.get("cash_balance", "0"),
            cash_available=data.get("cash_available", "0"),
            draw_balance=data.get("draw_balance"),
            today_profit=data.get("today_profit"),
            account_type=data.get("account_type"),
            accu_profit=data.get("accu_profit"),
            fund_name=data.get("fund_name"),
            fund_code=data.get("fund_code"),
            frozen_funds_total=data.get("frozen_funds_total"),
            frozen_funds_detail=data.get("frozen_funds_detail"),
            in_transit_asset_total=data.get("in_transit_asset_total"),
            in_transit_asset_detail=data.get("in_transit_asset_detail"),
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
