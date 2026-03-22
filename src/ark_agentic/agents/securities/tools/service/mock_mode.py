"""Mock 模式判断"""

import os
from typing import Any


def get_mock_mode() -> bool:
    """服务级默认 mock 状态（来自 SECURITIES_SERVICE_MOCK 环境变量）"""
    return os.getenv("SECURITIES_SERVICE_MOCK", "").lower() in ("true", "1")


def get_mock_mode_for_context(context: dict | None = None) -> bool:
    """per-request mock 模式解析

    优先级：
    1. context 中的 user:mock_mode（per-session 覆盖，由前端随请求携带）
    2. SECURITIES_SERVICE_MOCK 环境变量（服务级默认）
    """
    if context:
        val = context.get("user:mock_mode") or context.get("mock_mode")
        if val is not None:
            return str(val).lower() in ("true", "1")
    return get_mock_mode()
