"""API 参数映射工具

用于从 context 构建真实 API 请求体。
支持 user: 前缀和裸 key 兼容（优先 user: 前缀）。
"""

from __future__ import annotations

from .service_client import get_mock_mode_for_context
from typing import Any, Callable


def _get_context_value(
    context: dict[str, Any] | None, key: str, default: Any = None
) -> Any:
    """从 context 获取值，优先 user: 前缀，兼容裸 key

    Args:
        context: 上下文字典
        key: 键名（不含前缀）
        default: 默认值

    Returns:
        找到的值或默认值
    """
    if context is None:
        return default
    # 优先 user: 前缀
    prefixed = f"user:{key}"
    if prefixed in context:
        return context[prefixed]
    # 兼容裸 key
    if key in context:
        return context[key]
    return default


def build_api_request(
    config: dict[str, tuple],
    context: dict[str, Any],
) -> dict[str, Any]:
    """根据配置构建 API 请求体

    Args:
        config: 参数映射配置
            格式: {"api_field": ("source_type", source_value, transform?), ...}
            - source_type: "static" | "context" | "transform"
            - source_value: 静态值或 context 中的键（支持 user: 前缀自动兼容）
            - transform: 可选的转换函数（仅 transform 类型需要）
        context: 上下文字典（支持 user: 前缀和裸 key，优先 user: 前缀）

    Returns:
        API 请求体字典

    Example:
        >>> config = {
        ...     "channel": ("static", "native"),
        ...     "tokenId": ("context", "token_id"),
        ...     "body.accountType": ("transform", "account_type",
        ...                          lambda x: "2" if x == "margin" else "1"),
        ... }
        >>> context = {"user:token_id": "xxx", "user:account_type": "normal"}
        >>> build_api_request(config, context)
        {"channel": "native", "tokenId": "xxx", "body": {"accountType": "1"}}
    """
    result: dict[str, Any] = {}

    for api_field, source_def in config.items():
        source_type = source_def[0]

        if source_type == "static":
            # 静态值
            value = source_def[1]
        elif source_type == "context":
            # 从 context 中获取（支持 user: 前缀自动兼容）
            key = source_def[1]
            value = _get_context_value(context, key)
        elif source_type == "transform":
            # 从 context 获取并转换（支持 user: 前缀自动兼容）
            key = source_def[1]
            transform: Callable[[Any], Any] = source_def[2]
            raw_value = _get_context_value(context, key)
            # 始终调用 transform 函数，让它处理 None/默认值的情况
            value = transform(raw_value)
        else:
            continue

        # 只有非 None 值才设置
        if value is not None:
            _set_by_path(result, api_field, value)

    return result


def build_api_headers(
    header_config: dict[str, tuple],
    context: dict[str, Any],
) -> dict[str, str]:
    """根据配置构建 API Headers

    Args:
        header_config: Header 配置
            格式: {"header_name": ("context", key), ...}
        context: 上下文字典（支持 user: 前缀和裸 key，优先 user: 前缀）

    Returns:
        Headers 字典
    """
    headers: dict[str, str] = {}

    for header_name, source_def in header_config.items():
        if source_def[0] == "context":
            key = source_def[1]
            value = _get_context_value(context, key)
            if value:
                headers[header_name] = str(value)

    return headers


def _get_by_path(data: dict[str, Any] | None, path: str) -> Any:
    """通过点号路径获取嵌套值

    Args:
        data: 数据字典
        path: 点号分隔的路径，如 "token_id" 或 "user.profile.name"

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


def _set_by_path(data: dict[str, Any], path: str, value: Any) -> None:
    """通过点号路径设置嵌套值

    Args:
        data: 数据字典
        path: 点号分隔的路径，如 "body.accountType"
        value: 要设置的值

    Example:
        >>> data = {}
        >>> _set_by_path(data, "body.accountType", "1")
        >>> data
        {"body": {"accountType": "1"}}
    """
    keys = path.split(".")
    current: dict[str, Any] = data

    # 创建嵌套结构
    for key in keys[:-1]:
        if key not in current:
            current[key] = {}
        elif not isinstance(current[key], dict):
            # 如果中间节点不是字典，覆盖为字典
            current[key] = {}
        current = current[key]

    # 设置最终值
    current[keys[-1]] = value


# ============ validatedata 支持 ============


def parse_validatedata(s: str) -> dict[str, str]:
    """解析 validatedata 字符串为字典

    Args:
        s: validatedata 字符串，格式: key1=value1&key2=value2&...

    Returns:
        解析后的键值字典，忽略格式不正确的片段

    Example:
        >>> parse_validatedata("channel=REST&usercode=123&account=331012302926")
        {"channel": "REST", "usercode": "123", "account": "331012302926"}
    """
    result: dict[str, str] = {}
    for part in s.split("&"):
        if "=" in part:
            key, _, value = part.partition("=")
            key = key.strip()
            if key:
                result[key] = value
    return result


def _loginflag_to_account_type(loginflag: str | None) -> str:
    """将 loginflag 转换为账户类型

    loginflag=5 为两融账户，其余均为普通账户。
    """
    return "margin" if loginflag == "5" else "normal"


def enrich_securities_context(input_context: dict[str, Any]) -> dict[str, Any]:
    """证券 Agent context 预处理：解析 validatedata 字符串并将各字段注入 context

    由 AgentRunner.context_preprocessor 调用，在合并 session.state 之前执行。
    已存在的显式字段不会被覆盖。

    account_type 推导规则（优先级从高到低）：
      1. 显式传入的 user:account_type
      2. validatedata 中的 loginflag（5=两融，其余=普通）
    """
    raw = input_context.get("user:validatedata")
    if not raw:
        return input_context

    enriched = dict(input_context)
    for field, val in parse_validatedata(str(raw)).items():
        prefixed = f"user:{field}"
        if prefixed not in enriched:
            enriched[prefixed] = val

    # 从 loginflag 推导 account_type（不覆盖显式传入的值）
    if "user:account_type" not in enriched:
        loginflag = enriched.get("user:loginflag")
        enriched["user:account_type"] = _loginflag_to_account_type(loginflag)

    return enriched


def build_validatedata(
    context: dict[str, Any] | None,
    skip_on_mock: bool = True,
) -> str:
    """从 context 获取 validatedata 字符串

    Args:
        context: 上下文字典（支持 user: 前缀和裸 key）
        skip_on_mock: Mock 模式下返回空字符串，默认 True

    Returns:
        validatedata 原始字符串，Mock 模式下返回空字符串
    """
    if skip_on_mock and get_mock_mode_for_context(context):
        return ""
    return _get_context_value(context, "validatedata") or ""


def build_api_headers_with_validatedata(
    header_config: dict[str, tuple],
    context: dict[str, Any] | None,
) -> dict[str, str]:
    """构建包含 validatedata 的 API Headers

    Args:
        header_config: Header 配置
            格式: {"header_name": ("validatedata", "build") | ("context", key), ...}
        context: 上下文字典（支持 user: 前缀和裸 key）

    Returns:
        Headers 字典，包含 validatedata 和 signature

    Example:
        >>> header_config = {
        ...     "validatedata": ("validatedata", "build"),
        ...     "signature": ("context", "signature"),
        ... }
        >>> context = {
        ...     "user:validatedata": "channel=REST&usercode=150573383&...",
        ...     "user:signature": "xxx",
        ... }
        >>> headers = build_api_headers_with_validatedata(header_config, context)
        >>> "validatedata" in headers
        True
    """
    headers: dict[str, str] = {}

    if context is None:
        return headers

    for header_name, source_def in header_config.items():
        source_type = source_def[0]

        if source_type == "context":
            key = source_def[1]
            value = _get_context_value(context, key)
            if value:
                headers[header_name] = str(value)
        elif source_type == "validatedata":
            # 构建 validatedata 字符串
            validatedata_str = build_validatedata(context)
            if validatedata_str:  # 非空时才添加（Mock 模式可能为空）
                headers[header_name] = validatedata_str

    return headers


# ============ 服务参数配置 ============

# 账户总览 API 参数配置
# context 为扁平结构: {"token_id": "xxx", "account_type": "normal", "user_id": "U001"}
ACCOUNT_OVERVIEW_PARAM_CONFIG: dict[str, tuple] = {
    # API 字段 -> (来源类型, 来源值, [转换函数])
    "channel": ("static", "native"),
    "appName": ("static", "AYLCAPP"),
    "tokenId": ("context", "token_id"),  # 从扁平 context 获取
    "body.accountType": (
        "transform",
        "account_type",  # 从扁平 context 获取
        lambda x: "2" if x == "margin" else ("1" if x else None),  # None if missing
    ),
}

# 现金资产 API 参数配置
# 与 account_overview 使用相同的请求格式
CASH_ASSETS_PARAM_CONFIG: dict[str, tuple] = {
    # API 字段 -> (来源类型, 来源值, [转换函数])
    "channel": ("static", "native"),
    "appName": ("static", "AYLCAPP"),
    "tokenId": ("context", "token_id"),  # 从扁平 context 获取
    "body.accountType": (
        "transform",
        "account_type",  # 从扁平 context 获取
        lambda x: "2" if x == "margin" else ("1" if x else None),  # None if missing
    ),
}

# ETF 持仓 API 参数配置
# 注意：ETF API 请求体结构与 account_overview/cash_assets 不同
# assetGrpType 转换规则：普通户 -> 5, 两融户 -> 7
ETF_HOLDINGS_PARAM_CONFIG: dict[str, tuple] = {
    # Body 参数 - ETF API 使用不同的请求结构
    "assetGrpType": (
        "transform",
        "account_type",  # 从 context 获取 account_type
        lambda x: 7 if x == "margin" else 5,  # margin -> 7, normal/other -> 5
    ),
    "appName": ("static", "AYLCAPP"),
    "limit": ("transform", "limit", lambda x: x if x else 20),  # 默认 20 条
}

# ETF 持仓 Header 认证配置
# ETF API 需要特殊的 header 认证
ETF_HOLDINGS_HEADER_CONFIG: dict[str, tuple] = {
    "validatedata": ("validatedata", "build"),  # 自动构建 validatedata
    "signature": ("context", "signature"),  # 从 context 获取
}

# 港股通持仓 API 参数配置
# 注意：HKSC API 请求体结构与 ETF 类似但略有不同
HKSC_HOLDINGS_PARAM_CONFIG: dict[str, tuple] = {
    # Body 参数
    "appName": ("static", "AYLCAPP"),
    "model": ("transform", "model", lambda x: x if x else 1),  # 默认 1
    "limit": ("transform", "limit", lambda x: x if x else 20),  # 默认 20 条
}

# Header 参数配置（HKSC 专用，与 ETF 相同）
HKSC_HOLDINGS_HEADER_CONFIG: dict[str, tuple] = {
    "validatedata": ("validatedata", "build"),  # 自动构建 validatedata
    "signature": ("context", "signature"),  # 从 context 获取
}

# 统一的 Header 认证配置（所有服务共用）
# 使用 validatedata + signature 认证方式
UNIFIED_HEADER_CONFIG: dict[str, tuple] = {
    "validatedata": ("validatedata", "build"),  # 自动构建 validatedata
    "signature": ("context", "signature"),  # 从 context 获取
}

# 基金理财持仓 API 参数配置（HTTP GET query params）
FUND_HOLDINGS_PARAM_CONFIG: dict[str, tuple] = {
    "usercode": ("context", "usercode"),  # 来自 user:usercode 或 usercode
    "channel":  ("static", "10014"),      # 固定值 10014
}

# 服务参数配置注册表
SERVICE_PARAM_CONFIGS: dict[str, dict[str, tuple]] = {
    "account_overview": ACCOUNT_OVERVIEW_PARAM_CONFIG,
    "cash_assets": CASH_ASSETS_PARAM_CONFIG,
    "etf_holdings": ETF_HOLDINGS_PARAM_CONFIG,
    "hksc_holdings": HKSC_HOLDINGS_PARAM_CONFIG,
    "fund_holdings": FUND_HOLDINGS_PARAM_CONFIG,
}

# 服务 Header 配置注册表（用于需要特殊 header 的服务）
SERVICE_HEADER_CONFIGS: dict[str, dict[str, tuple]] = {
    "account_overview": UNIFIED_HEADER_CONFIG,  # 账户总览使用 validatedata
    "cash_assets": UNIFIED_HEADER_CONFIG,       # 现金资产使用 validatedata
    "fund_holdings": UNIFIED_HEADER_CONFIG,     # 基金持仓使用 validatedata
    "security_detail": UNIFIED_HEADER_CONFIG,   # 标的详情使用 validatedata
    "etf_holdings": ETF_HOLDINGS_HEADER_CONFIG,  # ETF 使用 validatedata
    "hksc_holdings": HKSC_HOLDINGS_HEADER_CONFIG,  # HKSC 使用 validatedata
    "branch_info": UNIFIED_HEADER_CONFIG,       # 开户营业部查询使用 validatedata
}
