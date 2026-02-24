"""API 响应字段提取工具

用于从 API 响应中提取显示所需的字段，支持多种响应格式。
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

# 真实 API 格式字段映射
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

# 旧格式字段映射（向后兼容）
ACCOUNT_OVERVIEW_LEGACY_MAPPING: dict[str, str] = {
    "total_assets": "data.totalAssets",
    "cash_balance": "data.cashBalance",
    "stock_market_value": "data.stockValue",
    "fund_market_value": "data.fundMarketValue",
    "today_profit": "data.todayProfit",
    "total_profit": "data.totalProfit",
    "profit_rate": "data.profitRate",
    # 两融字段
    "margin_ratio": "data.marginRatio",
    "risk_level": "data.riskLevel",
    "maintenance_margin": "data.maintenanceMargin",
    "available_margin": "data.availableMargin",
}


def extract_account_overview(data: dict[str, Any]) -> dict[str, Any]:
    """提取账户总览字段（自动检测格式）
    
    自动检测 API 响应格式，选择对应的字段映射进行提取。
    
    Args:
        data: API 响应数据
    
    Returns:
        提取后的字段字典
    """
    # 检测真实 API 格式：有 results.rmb 结构
    if "results" in data and isinstance(data.get("results"), dict):
        results = data["results"]
        if "rmb" in results and isinstance(results.get("rmb"), dict):
            return extract_fields(data, ACCOUNT_OVERVIEW_FIELD_MAPPING)
    
    # 使用旧格式
    return extract_fields(data, ACCOUNT_OVERVIEW_LEGACY_MAPPING)


def detect_response_format(data: dict[str, Any]) -> str:
    """检测响应格式类型
    
    Args:
        data: API 响应数据
    
    Returns:
        格式类型: "real" 或 "legacy"
    """
    if "results" in data and isinstance(data.get("results"), dict):
        results = data["results"]
        if "rmb" in results:
            return "real"
    return "legacy"


# ============ 现金资产字段映射 ============

# 真实 API 格式字段映射
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

# 旧格式字段映射（向后兼容）
CASH_ASSETS_LEGACY_MAPPING: dict[str, str] = {
    "available_cash": "data.availableCash",
    "frozen_cash": "data.frozenCash",
    "total_cash": "data.totalCash",
    "update_time": "data.updateTime",
}


def extract_cash_assets(data: dict[str, Any]) -> dict[str, Any]:
    """提取现金资产字段（自动检测格式）
    
    自动检测 API 响应格式，选择对应的字段映射进行提取。
    
    Args:
        data: API 响应数据
    
    Returns:
        提取后的字段字典
    """
    # 检测真实 API 格式：有 results.rmb 结构
    if "results" in data and isinstance(data.get("results"), dict):
        results = data["results"]
        if "rmb" in results and isinstance(results.get("rmb"), dict):
            return extract_fields(data, CASH_ASSETS_FIELD_MAPPING)
    
    # 使用旧格式
    return extract_fields(data, CASH_ASSETS_LEGACY_MAPPING)


# ============ 服务字段配置注册表 ============

# 存储每个服务的字段提取配置
SERVICE_FIELD_MAPPINGS: dict[str, dict[str, dict[str, str]]] = {
    "account_overview": {
        "real": ACCOUNT_OVERVIEW_FIELD_MAPPING,
        "legacy": ACCOUNT_OVERVIEW_LEGACY_MAPPING,
    },
    "cash_assets": {
        "real": CASH_ASSETS_FIELD_MAPPING,
        "legacy": CASH_ASSETS_LEGACY_MAPPING,
    },
}


def extract_service_fields(
    service_name: str,
    data: dict[str, Any],
) -> dict[str, Any]:
    """提取指定服务的字段（自动检测格式）
    
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
    
    # 其他服务默认返回原始数据
    return data