"""服务基础设施"""

import logging
import os
from typing import Any

from .adapters import ADAPTER_REGISTRY
from .base import (
    BaseServiceAdapter,
    ServiceConfig,
    ServiceError,
    build_validatedata_request,
    check_api_response,
    require_context_fields,
)
from .mock_loader import MockServiceAdapter, get_mock_loader
from .mock_mode import get_mock_mode, get_mock_mode_for_context
from .stock_search_service import StockSearchService

logger = logging.getLogger(__name__)

__all__ = [
    "ServiceConfig",
    "BaseServiceAdapter",
    "ServiceError",
    "require_context_fields",
    "build_validatedata_request",
    "check_api_response",
    "get_mock_mode",
    "get_mock_mode_for_context",
    "get_mock_loader",
    "MockServiceAdapter",
    "ADAPTER_REGISTRY",
    "create_service_adapter",
    "StockSearchService",
]


def create_service_adapter(
    service_name: str,
    context: dict | None = None,
) -> BaseServiceAdapter:
    """创建服务适配器

    Args:
        service_name: 服务名称（account_overview, etf_holdings等）
        context: 请求上下文，用于解析 per-session mock 设置

    Returns:
        服务适配器实例
    """
    session_override = (
        context
        and context.get("user:mock_mode")
        or (context and context.get("mock_mode"))
    )
    is_mock = get_mock_mode_for_context(context)
    source = "session" if session_override is not None else "env_default"
    mode_label = "[MOCK]" if is_mock else "[API] "
    logger.info("%s tool=%-20s source=%s", mode_label, service_name, source)

    if is_mock:
        return MockServiceAdapter(service_name)

    url = os.getenv(f"SECURITIES_{service_name.upper()}_URL")
    if not url:
        raise ValueError(
            f"Missing environment variable: SECURITIES_{service_name.upper()}_URL"
        )

    config = ServiceConfig(
        url=url,
        auth_type=os.getenv(f"SECURITIES_{service_name.upper()}_AUTH_TYPE", "header"),
        auth_key=os.getenv(
            f"SECURITIES_{service_name.upper()}_AUTH_KEY", "Authorization"
        ),
        auth_value=os.getenv(f"SECURITIES_{service_name.upper()}_AUTH_VALUE"),
    )

    adapter_class = ADAPTER_REGISTRY.get(service_name)
    if adapter_class:
        return adapter_class(config)

    raise ValueError(f"Unknown service: {service_name}")
