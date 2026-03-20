"""
证券服务客户端适配层

统一管理多个服务接口的调用和数据标准化。
"""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from typing import Any

import httpx

from .mock_loader import get_mock_loader

logger = logging.getLogger(__name__)


class ServiceConfig:
    """服务配置"""

    def __init__(
        self,
        url: str,
        auth_type: str = "header",  # "header" or "body"
        auth_key: str = "Authorization",
        auth_value: str | None = None,
        timeout: float = 30.0,
    ):
        self.url = url
        self.auth_type = auth_type
        self.auth_key = auth_key
        self.auth_value = auth_value
        self.timeout = timeout


class BaseServiceAdapter(ABC):
    """服务适配器基类"""

    http_method: str = "POST"  # 子类可覆盖为 "GET"

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

        # 构建请求
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

        # 解析和标准化
        raw_data = resp.json()
        return self._normalize_response(raw_data, account_type)

    def _build_request(
        self,
        account_type: str,
        user_id: str,
        params: dict[str, Any],
    ) -> tuple[dict[str, str], dict[str, Any]]:
        """构建请求 headers 和 payload（POST 时为 JSON body，GET 时为 query params）"""
        headers = {"Content-Type": "application/json"}
        payload = {"user_id": user_id, "account_type": account_type, **params}

        # 添加认证
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


def _require_context_fields(
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
    from .param_mapping import _get_context_value

    if get_mock_mode_for_context(context):
        return

    missing = [f for f in fields if not _get_context_value(context, f)]
    if missing:
        prefix = f"[{service_name}] " if service_name else ""
        raise ValueError(f"{prefix}context 缺少必需字段: {', '.join(missing)}")


class AccountOverviewAdapter(BaseServiceAdapter):
    """账户总资产服务适配器

    使用 validatedata + signature 认证：
    - Headers: {"validatedata": "...", "signature": "..."}
    - 请求体: {"channel": "native", "appName": "AYLCAPP", "body": {"accountType": "1"}}
    - 响应体: {"status": 1, "results": {"rmb": {...}}}
    """

    def _build_request(
        self,
        account_type: str,
        user_id: str,
        params: dict[str, Any],
    ) -> tuple[dict[str, str], dict[str, Any]]:
        """构建请求（使用 validatedata + signature 认证）

        context 为扁平结构: {"channel": "REST", "usercode": "...", "signature": "...", ...}
        """
        from .param_mapping import (
            build_api_request,
            build_api_headers_with_validatedata,
            SERVICE_PARAM_CONFIGS,
            SERVICE_HEADER_CONFIGS,
        )

        # 从 params 中获取 context（扁平结构）
        context = params.get("_context", {})
        _require_context_fields(context, ["validatedata"], "account_overview")

        # 确保扁平结构中有 account_type
        if "account_type" not in context:
            context = {**context, "account_type": account_type}

        # 使用参数映射构建请求体
        config = SERVICE_PARAM_CONFIGS.get("account_overview", {})
        body = build_api_request(config, context)

        # 使用 build_api_headers_with_validatedata 构建认证 headers
        # （包含 validatedata 和 signature）
        headers = {"Content-Type": "application/json"}
        header_config = SERVICE_HEADER_CONFIGS.get("account_overview", {})
        auth_headers = build_api_headers_with_validatedata(header_config, context)
        headers.update(auth_headers)

        # 添加配置的认证（如果有的话，作为 fallback）
        if self.config.auth_type == "header" and self.config.auth_value:
            if self.config.auth_key not in headers:  # 不覆盖 validatedata/signature
                headers[self.config.auth_key] = self.config.auth_value

        return headers, body

    def _normalize_response(
        self,
        raw_data: dict[str, Any],
        account_type: str,
    ) -> dict[str, Any]:
        """返回原始数据，不做标准化（由 display_card 处理字段提取）"""
        # 检查 API 响应状态
        if raw_data.get("status") != 1:
            error_msg = raw_data.get("errmsg") or "Unknown API error"
            raise ServiceError(f"API returned error: {error_msg}")

        # 返回原始数据，字段提取由 display_card 工具完成
        return raw_data


class ETFHoldingsAdapter(BaseServiceAdapter):
    """ETF 持仓服务适配器

    使用 validatedata + signature 认证：
    - Headers: {"Content-Type": "application/json", "validatedata": "...", "signature": "..."}
    - 请求体: {"assetGrpType": 7, "appName": "AYLCAPP", "limit": 20}
    - 响应体: {"status": 1, "results": {"stockList": [...]}}
    """

    def _build_request(
        self,
        account_type: str,
        user_id: str,
        params: dict[str, Any],
    ) -> tuple[dict[str, str], dict[str, Any]]:
        """构建请求（使用 validatedata + signature 认证）"""
        from .param_mapping import (
            build_api_request,
            build_api_headers_with_validatedata,
            SERVICE_PARAM_CONFIGS,
            SERVICE_HEADER_CONFIGS,
        )

        context = params.get("_context", {})
        _require_context_fields(context, ["validatedata"], "etf_holdings")

        # 使用参数映射构建请求体
        config = SERVICE_PARAM_CONFIGS.get("etf_holdings", {})
        body = build_api_request(config, context)

        # 构建 headers（包含 validatedata 和 signature）
        headers = {"Content-Type": "application/json"}
        header_config = SERVICE_HEADER_CONFIGS.get("etf_holdings", {})
        auth_headers = build_api_headers_with_validatedata(header_config, context)
        headers.update(auth_headers)

        # 添加配置的认证（如果有的话，作为 fallback）
        if self.config.auth_type == "header" and self.config.auth_value:
            if self.config.auth_key not in headers:  # 不覆盖 validatedata/signature
                headers[self.config.auth_key] = self.config.auth_value

        return headers, body

    def _normalize_response(
        self,
        raw_data: dict[str, Any],
        account_type: str,
    ) -> dict[str, Any]:
        """返回原始数据，不做标准化（由 display_card 处理字段提取）"""
        # 检查 API 响应状态
        if raw_data.get("status") != 1:
            error_msg = raw_data.get("msg") or "Unknown API error"
            raise ServiceError(f"API returned error: {error_msg}")

        # 返回原始数据，字段提取由 display_card 工具完成
        return raw_data


class HKSCHoldingsAdapter(BaseServiceAdapter):
    """港股通持仓服务适配器

    使用 validatedata + signature 认证：
    - Headers: {"Content-Type": "application/json", "validatedata": "...", "signature": "..."}
    - 请求体: {"appName": "AYLCAPP", "model": 1, "limit": 20}
    - 响应体: {"status": 1, "results": {"stockList": [...], "holdMktVal": ...}}
    """

    def _build_request(
        self,
        account_type: str,
        user_id: str,
        params: dict[str, Any],
    ) -> tuple[dict[str, str], dict[str, Any]]:
        """构建请求（使用 validatedata + signature 认证）"""
        from .param_mapping import (
            build_api_request,
            build_api_headers_with_validatedata,
            SERVICE_PARAM_CONFIGS,
            SERVICE_HEADER_CONFIGS,
        )

        context = params.get("_context", {})
        _require_context_fields(context, ["validatedata"], "hksc_holdings")

        # 使用参数映射构建请求体
        config = SERVICE_PARAM_CONFIGS.get("hksc_holdings", {})
        body = build_api_request(config, context)

        # 构建 headers（包含 validatedata 和 signature）
        headers = {"Content-Type": "application/json"}
        header_config = SERVICE_HEADER_CONFIGS.get("hksc_holdings", {})
        auth_headers = build_api_headers_with_validatedata(header_config, context)
        headers.update(auth_headers)

        # 添加配置的认证（如果有的话，作为 fallback）
        if self.config.auth_type == "header" and self.config.auth_value:
            if self.config.auth_key not in headers:  # 不覆盖 validatedata/signature
                headers[self.config.auth_key] = self.config.auth_value

        return headers, body

    def _normalize_response(
        self,
        raw_data: dict[str, Any],
        account_type: str,
    ) -> dict[str, Any]:
        """返回原始数据，不做标准化（由 display_card 处理字段提取）"""
        # 检查 API 响应状态
        if raw_data.get("status") != 1:
            error_msg = (
                raw_data.get("errmsg") or raw_data.get("msg") or "Unknown API error"
            )
            raise ServiceError(f"API returned error: {error_msg}")

        # 返回原始数据，字段提取由 display_card 工具完成
        return raw_data


class FundHoldingsAdapter(BaseServiceAdapter):
    """基金理财持仓服务适配器

    HTTP GET，query params 传递 usercode 和 channel：
    - GET /api?usercode=xxx&channel=xxx
    - Headers: {"validatedata": "...", "signature": "..."}
    """

    http_method = "GET"

    def _build_request(
        self,
        account_type: str,
        user_id: str,
        params: dict[str, Any],
    ) -> tuple[dict[str, str], dict[str, Any]]:
        """构建 GET 请求（query params: usercode + channel）"""
        from .param_mapping import (
            build_api_request,
            build_api_headers_with_validatedata,
            SERVICE_PARAM_CONFIGS,
            SERVICE_HEADER_CONFIGS,
        )

        context = params.get("_context", {})
        _require_context_fields(context, ["validatedata", "usercode", "channel"], "fund_holdings")

        # query params: usercode + channel
        param_config = SERVICE_PARAM_CONFIGS.get("fund_holdings", {})
        query = build_api_request(param_config, context)

        # headers: validatedata + signature
        headers = {"Content-Type": "application/json"}
        header_config = SERVICE_HEADER_CONFIGS.get("fund_holdings", {})
        auth_headers = build_api_headers_with_validatedata(header_config, context)
        headers.update(auth_headers)

        if self.config.auth_type == "header" and self.config.auth_value:
            if self.config.auth_key not in headers:
                headers[self.config.auth_key] = self.config.auth_value

        return headers, query

    def _normalize_response(
        self,
        raw_data: dict[str, Any],
        account_type: str,
    ) -> dict[str, Any]:
        """使用 Pydantic 标准化字段"""
        from ..schemas import FundHoldingsSchema
        from pydantic import ValidationError

        data = raw_data.get("data", {})

        try:
            schema = FundHoldingsSchema.from_raw_data(data)
            return schema.model_dump()
        except ValidationError as e:
            logger.error(f"Fund holdings data validation failed: {e}")
            raise ServiceError(f"Invalid fund data: {e}")


class CashAssetsAdapter(BaseServiceAdapter):
    """现金资产服务适配器

    使用 validatedata + signature 认证：
    - Headers: {"validatedata": "...", "signature": "..."}
    - 请求体: {"channel": "native", "appName": "AYLCAPP", "body": {"accountType": "1"}}
    - 响应体: {"status": 1, "results": {"rmb": {...}}}
    """

    def _build_request(
        self,
        account_type: str,
        user_id: str,
        params: dict[str, Any],
    ) -> tuple[dict[str, str], dict[str, Any]]:
        """构建请求（使用 validatedata + signature 认证）

        context 为扁平结构: {"channel": "REST", "usercode": "...", "signature": "...", ...}
        """
        from .param_mapping import (
            build_api_request,
            build_api_headers_with_validatedata,
            SERVICE_PARAM_CONFIGS,
            SERVICE_HEADER_CONFIGS,
        )

        # 从 params 中获取 context（扁平结构）
        context = params.get("_context", {})
        _require_context_fields(context, ["validatedata"], "cash_assets")

        # 确保扁平结构中有 account_type
        if "account_type" not in context:
            context = {**context, "account_type": account_type}

        # 使用参数映射构建请求体
        config = SERVICE_PARAM_CONFIGS.get("cash_assets", {})
        body = build_api_request(config, context)

        # 使用 build_api_headers_with_validatedata 构建认证 headers
        # （包含 validatedata 和 signature）
        headers = {"Content-Type": "application/json"}
        header_config = SERVICE_HEADER_CONFIGS.get("cash_assets", {})
        auth_headers = build_api_headers_with_validatedata(header_config, context)
        headers.update(auth_headers)

        # 添加配置的认证（如果有的话，作为 fallback）
        if self.config.auth_type == "header" and self.config.auth_value:
            if self.config.auth_key not in headers:  # 不覆盖 validatedata/signature
                headers[self.config.auth_key] = self.config.auth_value

        return headers, body

    def _normalize_response(
        self,
        raw_data: dict[str, Any],
        account_type: str,
    ) -> dict[str, Any]:
        """返回原始数据，不做标准化（由 display_card 处理字段提取）"""
        # 检查 API 响应状态
        if raw_data.get("status") != 1:
            error_msg = raw_data.get("errmsg") or "Unknown API error"
            raise ServiceError(f"API returned error: {error_msg}")

        # 返回原始数据，字段提取由 display_card 工具完成
        return raw_data


class SecurityDetailAdapter(BaseServiceAdapter):
    """具体标的详情服务适配器

    使用 validatedata + signature 认证：
    - Headers: {"validatedata": "...", "signature": "..."}
    """

    def _build_request(
        self,
        account_type: str,
        user_id: str,
        params: dict[str, Any],
    ) -> tuple[dict[str, str], dict[str, Any]]:
        """构建请求（使用 validatedata + signature 认证）"""
        from .param_mapping import (
            build_api_headers_with_validatedata,
            SERVICE_HEADER_CONFIGS,
        )

        context = params.get("_context", {})
        _require_context_fields(context, ["validatedata"], "security_detail")

        # 构建请求体
        body = {"user_id": user_id, "account_type": account_type}

        # 构建 headers（包含 validatedata 和 signature）
        headers = {"Content-Type": "application/json"}
        header_config = SERVICE_HEADER_CONFIGS.get("security_detail", {})
        auth_headers = build_api_headers_with_validatedata(header_config, context)
        headers.update(auth_headers)

        # 添加配置的认证（如果有的话，作为 fallback）
        if self.config.auth_type == "header" and self.config.auth_value:
            if self.config.auth_key not in headers:  # 不覆盖 validatedata/signature
                headers[self.config.auth_key] = self.config.auth_value

        return headers, body

    def _normalize_response(
        self,
        raw_data: dict[str, Any],
        account_type: str,
    ) -> dict[str, Any]:
        """使用 Pydantic 标准化字段"""
        from ..schemas import SecurityDetailSchema
        from pydantic import ValidationError

        data = raw_data.get("data", {})

        try:
            schema = SecurityDetailSchema.from_raw_data(data)
            return schema.model_dump()
        except ValidationError as e:
            logger.error(f"Security detail data validation failed: {e}")
            raise ServiceError(f"Invalid security data: {e}")


class BranchInfoAdapter(BaseServiceAdapter):
    """开户营业部查询服务适配器

    使用 validatedata + signature 认证：
    - Headers: {"Content-Type": "application/json", "validatedata": "...", "signature": "..."}
    - 请求体: 空 body（{}）
    - 响应体: {"status": 1, "errMsg": "成功", "results": {"address": ..., "servicePhone": ..., "branchName": ..., "seatNo": {...}}}
    """

    def _build_request(
        self,
        account_type: str,
        user_id: str,
        params: dict[str, Any],
    ) -> tuple[dict[str, str], dict[str, Any]]:
        """构建请求（使用 validatedata + signature 认证，body 为空）"""
        from .param_mapping import (
            build_api_headers_with_validatedata,
            SERVICE_HEADER_CONFIGS,
        )

        context = params.get("_context", {})
        _require_context_fields(context, ["validatedata"], "branch_info")

        headers = {"Content-Type": "application/json"}
        header_config = SERVICE_HEADER_CONFIGS.get("branch_info", {})
        auth_headers = build_api_headers_with_validatedata(header_config, context)
        headers.update(auth_headers)

        if self.config.auth_type == "header" and self.config.auth_value:
            if self.config.auth_key not in headers:
                headers[self.config.auth_key] = self.config.auth_value

        return headers, {}

    def _normalize_response(
        self,
        raw_data: dict[str, Any],
        account_type: str,
    ) -> dict[str, Any]:
        """返回原始数据"""
        if raw_data.get("status") != 1:
            error_msg = raw_data.get("errMsg") or "Unknown API error"
            raise ServiceError(f"API returned error: {error_msg}")

        return raw_data


class MockServiceAdapter(BaseServiceAdapter):
    """Mock 服务适配器（从文件加载）"""

    def __init__(self, service_name: str):
        # 不需要真实配置
        super().__init__(ServiceConfig(url=""))
        self.service_name = service_name
        self._loader = get_mock_loader()

    async def call(
        self,
        account_type: str,
        user_id: str,
        **params: Any,
    ) -> dict[str, Any]:
        """从文件加载 Mock 数据"""

        # 根据账户类型选择场景
        scenario = "default"
        if self.service_name == "account_overview":
            scenario = "margin_user" if account_type == "margin" else "normal_user"
        elif self.service_name == "cash_assets":
            scenario = "margin_user" if account_type == "margin" else "normal_user"
        elif self.service_name == "etf_holdings":
            scenario = "default"  # ETF 不区分账户类型
        elif self.service_name == "hksc_holdings":
            scenario = "default"  # HKSC 不区分账户类型

        # 加载数据
        raw_data = self._loader.load(
            service_name=self.service_name,
            scenario=scenario,
            **params,
        )

        # 标准化（复用对应适配器的逻辑）
        return self._normalize_response(raw_data, account_type)

    def _normalize_response(self, raw_data, account_type):
        """标准化响应（根据服务类型调用对应适配器）"""
        # 根据服务名称选择对应的适配器进行标准化
        adapter_map = {
            "account_overview": AccountOverviewAdapter,
            "etf_holdings": ETFHoldingsAdapter,
            "hksc_holdings": HKSCHoldingsAdapter,
            "fund_holdings": FundHoldingsAdapter,
            "cash_assets": CashAssetsAdapter,
            "security_detail": SecurityDetailAdapter,
            "branch_info": BranchInfoAdapter,
        }

        adapter_class = adapter_map.get(self.service_name)
        if adapter_class:
            adapter = adapter_class(ServiceConfig(url=""))
            return adapter._normalize_response(raw_data, account_type)

        # 未知服务，返回原始数据
        return raw_data.get("data", {})


class ServiceError(Exception):
    """服务调用异常"""

    pass


# ============ Mock 模式解析 ============

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


def create_service_adapter(
    service_name: str,
    context: dict | None = None,
) -> BaseServiceAdapter:
    """创建服务适配器

    Args:
        service_name: 服务名称（account_overview, etf_holdings等）
        context: 请求上下文，用于解析 per-session mock 设置

    Returns:
        服务适配器实例，mock 状态由 get_mock_mode_for_context(context) 决定
    """
    # 判断 mock 来源，用于日志标注
    session_override = context and context.get("user:mock_mode") or (
        context and context.get("mock_mode")
    )
    is_mock = get_mock_mode_for_context(context)
    source = "session" if session_override is not None else "env_default"
    mode_label = "[MOCK]" if is_mock else "[API] "
    logger.info("%s tool=%-20s source=%s", mode_label, service_name, source)

    if is_mock:
        # 返回文件驱动的 Mock 适配器
        return MockServiceAdapter(service_name)

    # 从环境变量读取配置
    url = os.getenv(f"SECURITIES_{service_name.upper()}_URL")
    auth_type = os.getenv(f"SECURITIES_{service_name.upper()}_AUTH_TYPE", "header")
    auth_key = os.getenv(f"SECURITIES_{service_name.upper()}_AUTH_KEY", "Authorization")
    auth_value = os.getenv(f"SECURITIES_{service_name.upper()}_AUTH_VALUE")

    if not url:
        raise ValueError(
            f"Missing environment variable: SECURITIES_{service_name.upper()}_URL"
        )

    config = ServiceConfig(
        url=url,
        auth_type=auth_type,
        auth_key=auth_key,
        auth_value=auth_value,
    )

    # 根据服务名称返回对应适配器
    adapter_map = {
        "account_overview": AccountOverviewAdapter,
        "etf_holdings": ETFHoldingsAdapter,
        "hksc_holdings": HKSCHoldingsAdapter,
        "fund_holdings": FundHoldingsAdapter,
        "cash_assets": CashAssetsAdapter,
        "security_detail": SecurityDetailAdapter,
        "branch_info": BranchInfoAdapter,
    }

    adapter_class = adapter_map.get(service_name)
    if adapter_class:
        return adapter_class(config)

    raise ValueError(f"Unknown service: {service_name}")
