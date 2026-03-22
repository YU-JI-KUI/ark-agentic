"""服务适配器基类和公共工具"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class ServiceConfig:
    """服务配置"""

    def __init__(
        self,
        url: str,
        auth_type: str = "header",
        auth_key: str = "Authorization",
        auth_value: str | None = None,
        timeout: float = 30.0,
    ):
        self.url = url
        self.auth_type = auth_type
        self.auth_key = auth_key
        self.auth_value = auth_value
        self.timeout = timeout


class ServiceError(Exception):
    """服务调用异常"""

    pass


class BaseServiceAdapter(ABC):
    """服务适配器基类"""

    http_method: str = "POST"

    def __init__(self, config: ServiceConfig):
        self.config = config
        self._http: httpx.AsyncClient | None = None

    async def _get_http(self) -> httpx.AsyncClient:
        """获取 HTTP 客户端"""
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(
                timeout=httpx.Timeout(self.config.timeout, connect=10.0)
            )
        return self._http

    async def call(
        self,
        account_type: str,
        user_id: str,
        **params: Any,
    ) -> dict[str, Any]:
        """调用服务接口"""
        client = await self._get_http()
        headers, payload = self._build_request(account_type, user_id, params)

        try:
            if self.http_method == "GET":
                resp = await client.get(
                    self.config.url,
                    params=payload,
                    headers=headers,
                )
            else:
                resp = await client.post(
                    self.config.url,
                    json=payload,
                    headers=headers,
                )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.error(
                "service=%s method=%s url=%s status=%s payload=%s response=%s",
                type(self).__name__,
                self.http_method,
                self.config.url,
                exc.response.status_code,
                payload,
                exc.response.text[:500],
            )
            raise ServiceError(
                f"HTTP {exc.response.status_code}: {exc.response.text[:300]}"
            ) from exc
        except httpx.RequestError as exc:
            logger.error(
                "service=%s method=%s url=%s payload=%s error=%s",
                type(self).__name__,
                self.http_method,
                self.config.url,
                payload,
                exc,
            )
            raise ServiceError(f"Request failed: {exc}") from exc

        raw_data = resp.json()
        return self._normalize_response(raw_data, account_type)

    def _build_request(
        self,
        account_type: str,
        user_id: str,
        params: dict[str, Any],
    ) -> tuple[dict[str, str], dict[str, Any]]:
        """构建请求 headers 和 payload（子类可覆盖）"""
        headers = {"Content-Type": "application/json"}
        payload = {"user_id": user_id, "account_type": account_type, **params}

        if self.config.auth_type == "header":
            headers[self.config.auth_key] = self.config.auth_value or ""
        else:
            payload[self.config.auth_key] = self.config.auth_value or ""

        return headers, payload

    @abstractmethod
    def _normalize_response(
        self,
        raw_data: dict[str, Any],
        account_type: str,
    ) -> dict[str, Any]:
        """标准化响应数据（子类实现）"""
        pass

    async def close(self):
        """关闭 HTTP 客户端"""
        if self._http and not self._http.is_closed:
            await self._http.aclose()


def require_context_fields(
    context: dict[str, Any],
    fields: list[str],
    service_name: str = "",
) -> None:
    """校验 context 中必需字段，缺失则 raise ValueError（Mock 模式跳过）

    Args:
        context: 上下文字典（支持 user: 前缀和裸 key）
        fields: 必需字段名列表（不含前缀）
        service_name: 服务名称，用于错误信息
    """
    from .mock_mode import get_mock_mode_for_context
    from .param_mapping import _get_context_value

    if get_mock_mode_for_context(context):
        return

    missing = [f for f in fields if not _get_context_value(context, f)]
    if missing:
        prefix = f"[{service_name}] " if service_name else ""
        raise ValueError(f"{prefix}context 缺少必需字段: {', '.join(missing)}")


def build_validatedata_request(
    service_name: str,
    context: dict[str, Any],
    account_type: str | None = None,
) -> tuple[dict[str, str], dict[str, Any]]:
    """构建 validatedata + signature 认证请求

    公共方法，供所有需要这种认证方式的 Adapter 使用。

    Args:
        service_name: 服务名称 (account_overview, etf_holdings 等)
        context: 请求上下文
        account_type: 账户类型 (可选，某些服务需要)

    Returns:
        (headers, body) 元组
    """
    from .param_mapping import (
        build_api_request,
        build_api_headers_with_validatedata,
        SERVICE_PARAM_CONFIGS,
        SERVICE_HEADER_CONFIGS,
    )

    require_context_fields(context, ["validatedata"], service_name)

    if account_type and "account_type" not in context:
        context = {**context, "account_type": account_type}

    config = SERVICE_PARAM_CONFIGS.get(service_name, {})
    body = build_api_request(config, context)

    headers = {"Content-Type": "application/json"}
    header_config = SERVICE_HEADER_CONFIGS.get(service_name, {})
    auth_headers = build_api_headers_with_validatedata(header_config, context)
    headers.update(auth_headers)

    return headers, body


def check_api_response(raw_data: dict[str, Any]) -> None:
    """检查 API 响应状态"""
    if raw_data.get("status") != 1:
        error_msg = (
            raw_data.get("errmsg")
            or raw_data.get("msg")
            or raw_data.get("errMsg")
            or "Unknown API error"
        )
        raise ServiceError(f"API returned error: {error_msg}")
