"""API 参数映射工具

用于从 context 构建真实 API 请求体。
支持 user: 前缀和裸 key 兼容（优先 user: 前缀）。
"""

from __future__ import annotations

import os
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

# validatedata 必需字段列表
VALIDATEDATA_REQUIRED_FIELDS = [
    "channel",
    "usercode",
    "userid",
    "account",
    "branchno",
    "loginflag",
    "mobileNo",
]


def validate_validatedata_fields(
    context: dict[str, Any] | None,
    required_fields: list[str] | None = None,
    skip_on_mock: bool = True,
) -> list[str]:
    """校验 validatedata 必需字段是否存在

    Args:
        context: 上下文字典
        required_fields: 必需字段列表，默认使用 VALIDATEDATA_REQUIRED_FIELDS
        skip_on_mock: Mock 模式下跳过校验，默认 True

    Returns:
        缺失的字段列表（空列表表示全部存在）

    Example:
        >>> missing = validate_validatedata_fields(context)
        >>> if missing:
        ...     raise ValueError(f"缺少字段: {', '.join(missing)}")
    """
    # Mock 模式下跳过校验
    if skip_on_mock and os.getenv("SECURITIES_SERVICE_MOCK", "").lower() in ("true", "1"):
        return []

    if required_fields is None:
        required_fields = VALIDATEDATA_REQUIRED_FIELDS

    if context is None:
        return required_fields.copy()

    missing = []
    for field in required_fields:
        value = _get_context_value(context, field)
        if not value:
            missing.append(field)

    return missing


def build_validatedata(
    context: dict[str, Any] | None,
    required_fields: list[str] | None = None,
    skip_on_mock: bool = True,
) -> str:
    """从 context 构建 validatedata 字符串

    Args:
        context: 上下文字典（支持 user: 前缀和裸 key）
        required_fields: 必需字段列表，默认使用 VALIDATEDATA_REQUIRED_FIELDS
        skip_on_mock: Mock 模式下跳过校验并返回空字符串，默认 True

    Returns:
        validatedata 字符串，格式: key1=value1&key2=value2&...
        Mock 模式下返回空字符串

    Raises:
        ValueError: 如果缺少必需字段或字段值为空（非 Mock 模式）

    Example:
        >>> context = {
        ...     "user:channel": "REST",
        ...     "user:usercode": "150573383",
        ...     "user:userid": "12977997",
        ...     "user:account": "3310123",
        ...     "user:branchno": "3310",
        ...     "user:loginflag": "3",
        ...     "user:mobileNo": "137123123",
        ... }
        >>> build_validatedata(context)
        'channel=REST&usercode=150573383&userid=12977997&account=3310123&branchno=3310&loginflag=3&mobileNo=137123123'
    """
    # Mock 模式下返回空字符串
    if skip_on_mock and os.getenv("SECURITIES_SERVICE_MOCK", "").lower() in ("true", "1"):
        return ""

    if required_fields is None:
        required_fields = VALIDATEDATA_REQUIRED_FIELDS

    if context is None:
        raise ValueError(
            f"validatedata 构建失败：context 为空，需要字段: {', '.join(required_fields)}"
        )

    # 收集字段值
    parts = []
    missing_fields = []

    for field in required_fields:
        value = _get_context_value(context, field)
        if not value:
            missing_fields.append(field)
        else:
            parts.append(f"{field}={value}")

    if missing_fields:
        raise ValueError(
            f"validatedata 缺少必需字段或值为空: {', '.join(missing_fields)}"
        )

    return "&".join(parts)


def build_api_headers_with_validatedata(
    header_config: dict[str, tuple],
    context: dict[str, Any] | None,
) -> dict[str, str]:
    """构建包含 validatedata 的 API Headers

    与 build_api_headers 类似，但支持 validatedata 的自动构建。

    Args:
        header_config: Header 配置
            格式: {"header_name": ("validatedata", "build") | ("context", key), ...}
        context: 上下文字典（支持 user: 前缀和裸 key）

    Returns:
        Headers 字典，包含 validatedata 和 signature

    Raises:
        ValueError: 如果 validatedata 必需字段缺失（非 Mock 模式）

    Example:
        >>> header_config = {
        ...     "validatedata": ("validatedata", "build"),
        ...     "signature": ("context", "signature"),
        ... }
        >>> context = {
        ...     "user:channel": "REST",
        ...     "user:usercode": "150573383",
        ...     "user:signature": "xxx",
        ...     # ... 其他必需字段
        ... }
        >>> headers = build_api_headers_with_validatedata(header_config, context)
        >>> "validatedata" in headers
        True
        >>> "signature" in headers
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
    "channel":  ("context", "channel"),   # 来自 user:channel 或 channel
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
