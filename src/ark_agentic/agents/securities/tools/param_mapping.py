"""API 参数映射工具

用于从 context 构建真实 API 请求体。
"""

from __future__ import annotations

from typing import Any, Callable


def build_api_request(
    config: dict[str, tuple],
    context: dict[str, Any],
) -> dict[str, Any]:
    """根据配置构建 API 请求体
    
    Args:
        config: 参数映射配置
            格式: {"api_field": ("source_type", source_value, transform?), ...}
            - source_type: "static" | "context" | "transform"
            - source_value: 静态值或 context 中的键（支持点号分隔的嵌套路径）
            - transform: 可选的转换函数（仅 transform 类型需要）
        context: 上下文字典（扁平结构）
    
    Returns:
        API 请求体字典
    
    Example:
        >>> config = {
        ...     "channel": ("static", "native"),
        ...     "tokenId": ("context", "token_id"),
        ...     "body.accountType": ("transform", "account_type",
        ...                          lambda x: "2" if x == "margin" else "1"),
        ... }
        >>> context = {"token_id": "xxx", "account_type": "normal"}
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
            # 从 context 中获取
            key = source_def[1]
            value = _get_by_path(context, key)
        elif source_type == "transform":
            # 从 context 获取并转换
            key = source_def[1]
            transform: Callable[[Any], Any] = source_def[2]
            raw_value = _get_by_path(context, key)
            value = transform(raw_value) if raw_value is not None else None
        else:
            continue
        
        # 只有非 None 值才设置
        if value is not None:
            _set_by_path(result, api_field, value)
    
    return result


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
        lambda x: "2" if x == "margin" else "1",
    ),
}

# 服务参数配置注册表
SERVICE_PARAM_CONFIGS: dict[str, dict[str, tuple]] = {
    "account_overview": ACCOUNT_OVERVIEW_PARAM_CONFIG,
    # 其他服务可以在此添加
}