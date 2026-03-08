"""API 响应字段提取工具

用于从 API 响应中提取显示所需的字段。
"""

from __future__ import annotations

from typing import Any


def extract_fields(
    data: dict[str, Any],
    field_mapping: dict[str, str],
) -> dict[str, Any]:
    """从 API 响应提取指定字段
    
    Args:
        data: API 响应数据
        field_mapping: 字段映射配置
            格式: {"display_name": "api.path.to.field", ...}
    
    Returns:
        提取后的字段字典
    """
    result: dict[str, Any] = {}
    
    for display_name, api_path in field_mapping.items():
        value = _get_by_path(data, api_path)
        if value is not None:
            result[display_name] = value
    
    return result


def _get_by_path(data: dict[str, Any] | None, path: str) -> Any:
    """通过点号路径获取嵌套值
    
    Args:
        data: 数据字典
        path: 点号分隔的路径，如 "results.rmb.totalAssetVal"
    
    Returns:
        找到的值，未找到返回 None
    """
    if data is None:
        return None
    
    keys = path.split(".")
    value: Any = data
    
    for key in keys:
        if isinstance(value, dict) and key in value:
            value = value[key]
        else:
            return None
    
    return value


# ============ 账户总览字段映射 ============

ACCOUNT_OVERVIEW_FIELD_MAPPING: dict[str, str] = {
    # 显示字段名 -> API 响应路径
    "account_type": "results.accountType",
    "total_assets": "results.rmb.totalAssetVal",
    "cash_balance": "results.rmb.cashGainAssetsInfo.cashBalance",
    "stock_market_value": "results.rmb.mktAssetsInfo.totalMktVal",
    "fund_market_value": "results.rmb.fundMktAssetsInfo.fundMktVal",
    "today_profit": "results.rmb.mktAssetsInfo.totalMktProfitToday",
    "today_return_rate": "results.rmb.mktAssetsInfo.totalMktYieldToday",
    # 两融账户特有字段
    "net_assets": "results.rmb.rzrqAssetsInfo.netWorth",
    "total_liabilities": "results.rmb.rzrqAssetsInfo.totalLiabilities",
    "maintenance_margin_ratio": "results.rmb.rzrqAssetsInfo.mainRatio",
}


def extract_account_overview(data: dict[str, Any]) -> dict[str, Any]:
    """提取账户总览字段
    
    Args:
        data: API 响应数据
    
    Returns:
        提取后的字段字典
    """
    return extract_fields(data, ACCOUNT_OVERVIEW_FIELD_MAPPING)


# ============ 现金资产字段映射 ============

CASH_ASSETS_FIELD_MAPPING: dict[str, str] = {
    # 显示字段名 -> API 响应路径
    "account_type": "results.accountType",
    "cash_balance": "results.rmb.cashBalance",
    "cash_available": "results.rmb.available",
    "draw_balance": "results.rmb.avaliableDetail.drawBalance",
    "today_profit": "results.rmb.avaliableDetail.cashBalanceDetail.dayProfit",
    "accu_profit": "results.rmb.avaliableDetail.cashBalanceDetail.accuProfit",
    "fund_name": "results.rmb.avaliableDetail.cashBalanceDetail.fundName",
    "fund_code": "results.rmb.avaliableDetail.cashBalanceDetail.fundCode",
    "frozen_funds_total": "results.rmb.frozenFundsTotal",
    "frozen_funds_detail": "results.rmb.frozenFundsDetail",
    "in_transit_asset_total": "results.rmb.inTransitAssetTotal",
    "in_transit_asset_detail": "results.rmb.inTransitAssetDetail",
}


def extract_cash_assets(data: dict[str, Any]) -> dict[str, Any]:
    """提取现金资产字段
    
    Args:
        data: API 响应数据
    
    Returns:
        提取后的字段字典
    """
    return extract_fields(data, CASH_ASSETS_FIELD_MAPPING)


# ============ ETF 持仓字段映射 ============

# 汇总字段映射
ETF_HOLDINGS_FIELD_MAPPING: dict[str, str] = {
    "total": "results.total",
    "total_market_value": "results.dayTotalMktVal",
    "total_profit": "results.dayTotalPft",
    "total_profit_rate": "results.dayTotalPftRate",
    "account_type": "results.accountType",
}

# 列表项字段映射
ETF_HOLDINGS_ITEM_MAPPING: dict[str, str] = {
    "code": "secuCode",
    "name": "secuName",
    "hold_cnt": "holdCnt",
    "market_value": "mktVal",
    "day_profit": "dayPft",
    "day_profit_rate": "dayPftRate",
    "price": "price",
    "cost_price": "costPrice",
    "market_type": "marketType",
    "hold_position_profit": "holdPositionPft",
    "hold_position_profit_rate": "holdPositionPftRate",
}


def extract_list_items(
    items: list[dict[str, Any]],
    field_mapping: dict[str, str],
) -> list[dict[str, Any]]:
    """提取列表项字段
    
    Args:
        items: 原始列表数据
        field_mapping: 字段映射 {显示名: API字段名}
    
    Returns:
        提取后的列表数据
    """
    result = []
    for item in items:
        extracted = {}
        for display_name, api_field in field_mapping.items():
            value = item.get(api_field)
            if value is not None:
                extracted[display_name] = value
        result.append(extracted)
    return result


def extract_etf_holdings(data: dict[str, Any]) -> dict[str, Any]:
    """提取 ETF 持仓字段
    
    支持列表字段映射。
    
    Args:
        data: API 响应数据
    
    Returns:
        提取后的字段字典
    """
    results = data.get("results", {})
    
    # 提取汇总字段
    extracted = extract_fields(data, ETF_HOLDINGS_FIELD_MAPPING)
    
    # 提取列表字段
    stock_list = results.get("stockList", [])
    if stock_list:
        extracted["stock_list"] = extract_list_items(stock_list, ETF_HOLDINGS_ITEM_MAPPING)
    
    return extracted


# ============ 港股通持仓字段映射 ============

# 汇总字段映射
HKSC_HOLDINGS_FIELD_MAPPING: dict[str, str] = {
    "hold_market_value": "results.holdMktVal",
    "hold_position_profit": "results.holdPositionPft",
    "day_total_profit": "results.dayTotalPft",
    "day_total_profit_rate": "results.dayTotalPftRate",
    "total_hksc_share": "results.totalHkscShare",
    "available_hksc_share": "results.availableHkscShare",
    "limit_hksc_share": "results.limitHkscShare",
    "pre_frozen_asset": "results.preFrozenAsset",
    "progress": "results.progress",
}

# 列表项字段映射
HKSC_HOLDINGS_ITEM_MAPPING: dict[str, str] = {
    "code": "secuCode",
    "name": "secuName",
    "hold_cnt": "holdCnt",
    "share_bln": "shareBln",
    "market_value": "mktVal",
    "day_profit": "dayPft",
    "day_profit_rate": "dayPftRate",
    "price": "price",
    "cost_price": "costPrice",
    "market_type": "marketType",
    "hold_position_profit": "holdPositionPft",
    "hold_position_profit_rate": "holdPositionPftRate",
    "position": "position",
    "secu_acc": "secuAcc",
}

# 预冻结列表项字段映射
HKSC_PRE_FROZEN_ITEM_MAPPING: dict[str, str] = {
    "code": "secuCode",
    "name": "secuName",
    "pre_frozen_asset": "preFrozenAsset",
}


def extract_hksc_holdings(data: dict[str, Any]) -> dict[str, Any]:
    """提取港股通持仓字段
    
    支持列表字段映射，包括持仓列表和预冻结列表。
    
    Args:
        data: API 响应数据
    
    Returns:
        提取后的字段字典
    """
    results = data.get("results", {})
    
    # 提取汇总字段
    extracted = extract_fields(data, HKSC_HOLDINGS_FIELD_MAPPING)
    
    # 提取持仓列表字段
    stock_list = results.get("stockList", [])
    if stock_list:
        extracted["stock_list"] = extract_list_items(stock_list, HKSC_HOLDINGS_ITEM_MAPPING)
    
    # 提取预冻结列表字段（可选）
    pre_frozen_list = results.get("preFrozenStockList", [])
    if pre_frozen_list:
        extracted["pre_frozen_list"] = extract_list_items(pre_frozen_list, HKSC_PRE_FROZEN_ITEM_MAPPING)
    
    return extracted


# ============ 基金持仓字段映射 ============
# 输入为 FundHoldingsSchema.model_dump() 已标准化的 snake_case 数据


def extract_fund_holdings(data: dict[str, Any]) -> dict[str, Any]:
    """提取基金持仓字段

    输入为 FundHoldingsSchema.model_dump() 已标准化的数据，字段为 snake_case。
    输出统一为 stock_list 格式，与 ETF/HKSC 渲染路径兼容。

    Args:
        data: FundHoldingsSchema.model_dump() 返回的标准化数据

    Returns:
        提取后的字段字典，包含 stock_list 列表和汇总字段
    """
    holdings: list[dict[str, Any]] = data.get("holdings", [])
    summary: dict[str, Any] = data.get("summary", {})

    stock_list = [
        {
            "code": item.get("product_code"),
            "name": item.get("product_name"),
            "hold_cnt": item.get("quantity"),
            "market_value": item.get("market_value"),
            "day_profit": item.get("today_profit"),
            "cost_price": item.get("cost_price"),
            "current_value": item.get("current_value"),
            "hold_position_profit": item.get("profit"),
            "hold_position_profit_rate": item.get("profit_rate"),
        }
        for item in holdings
    ]

    return {
        "stock_list": stock_list,
        # total_market_value 供汇总栏"基金市值"使用
        "total_market_value": summary.get("total_market_value"),
        # day_total_profit → render_holdings_list_card 中作为 total_profit 的 fallback
        "day_total_profit": summary.get("today_profit"),
        # 累计盈亏，供前端扩展展示
        "hold_position_profit": summary.get("total_profit"),
        "hold_position_profit_rate": summary.get("total_profit_rate"),
    }


# ============ 开户营业部字段映射 ============

BRANCH_INFO_FIELD_MAPPING: dict[str, str] = {
    "branch_name": "results.branchName",
    "address": "results.address",
    "service_phone": "results.servicePhone",
}


def extract_branch_info(data: dict[str, Any]) -> dict[str, Any]:
    """提取开户营业部字段

    Args:
        data: API 响应数据

    Returns:
        提取后的字段字典，其中 service_phone 去除"营业部联系电话: "前缀
    """
    extracted = extract_fields(data, BRANCH_INFO_FIELD_MAPPING)

    # servicePhone 格式："营业部联系电话: 95511-8-9-2"，提取纯电话号码
    phone = extracted.get("service_phone", "")
    if isinstance(phone, str) and ": " in phone:
        extracted["service_phone"] = phone.split(": ", 1)[1]

    return extracted


# ============ 服务字段配置注册表 ============

SERVICE_FIELD_MAPPINGS: dict[str, dict[str, str]] = {
    "account_overview": ACCOUNT_OVERVIEW_FIELD_MAPPING,
    "cash_assets": CASH_ASSETS_FIELD_MAPPING,
    "etf_holdings": ETF_HOLDINGS_FIELD_MAPPING,
    "hksc_holdings": HKSC_HOLDINGS_FIELD_MAPPING,
}


def extract_service_fields(
    service_name: str,
    data: dict[str, Any],
) -> dict[str, Any]:
    """提取指定服务的字段
    
    Args:
        service_name: 服务名称
        data: API 响应数据
    
    Returns:
        提取后的字段字典
    """
    if service_name == "account_overview":
        return extract_account_overview(data)
    
    if service_name == "cash_assets":
        return extract_cash_assets(data)
    
    if service_name == "etf_holdings":
        return extract_etf_holdings(data)
    
    if service_name == "hksc_holdings":
        return extract_hksc_holdings(data)
    
    # 其他服务默认返回原始数据
    return data