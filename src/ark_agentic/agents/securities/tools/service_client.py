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
        headers, body = self._build_request(account_type, user_id, params)
        
        try:
            resp = await client.post(
                self.config.url,
                json=body,
                headers=headers,
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ServiceError(
                f"HTTP {exc.response.status_code}: {exc.response.text[:300]}"
            ) from exc
        except httpx.RequestError as exc:
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
        """构建请求 headers 和 body"""
        headers = {"Content-Type": "application/json"}
        body = {"user_id": user_id, "account_type": account_type, **params}
        
        # 添加认证
        if self.config.auth_type == "header":
            headers[self.config.auth_key] = self.config.auth_value or ""
        else:
            body[self.config.auth_key] = self.config.auth_value or ""
        
        return headers, body
    
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


class AccountOverviewAdapter(BaseServiceAdapter):
    """账户总资产服务适配器"""
    
    def _normalize_response(
        self,
        raw_data: dict[str, Any],
        account_type: str,
    ) -> dict[str, Any]:
        """使用 Pydantic 标准化字段"""
        from ..schemas import AccountOverviewSchema
        from pydantic import ValidationError
        
        data = raw_data.get("data", {})
        
        try:
            # 使用 Pydantic Schema 自动处理字段映射和类型校验
            schema = AccountOverviewSchema.from_raw_data(data, account_type)
            
            # 转换为字典
            result = schema.model_dump(exclude_none=True)
            
            # 如果是普通账户，移除两融字段
            if account_type == "normal":
                for key in ["margin_ratio", "risk_level", "maintenance_margin", "available_margin"]:
                    result.pop(key, None)
            
            return result
            
        except ValidationError as e:
            logger.error(f"Account overview data validation failed: {e}")
            raise ServiceError(f"Invalid response data: {e}")


class ETFHoldingsAdapter(BaseServiceAdapter):
    """ETF 持仓服务适配器"""
    
    def _normalize_response(
        self,
        raw_data: dict[str, Any],
        account_type: str,
    ) -> dict[str, Any]:
        """使用 Pydantic 标准化字段"""
        from ..schemas import ETFHoldingsSchema
        from pydantic import ValidationError
        
        data = raw_data.get("data", {})
        
        try:
            schema = ETFHoldingsSchema.from_raw_data(data)
            return schema.model_dump()
        except ValidationError as e:
            logger.error(f"ETF holdings data validation failed: {e}")
            raise ServiceError(f"Invalid ETF data: {e}")


class HKSCHoldingsAdapter(BaseServiceAdapter):
    """港股通持仓服务适配器"""
    
    def _normalize_response(
        self,
        raw_data: dict[str, Any],
        account_type: str,
    ) -> dict[str, Any]:
        """使用 Pydantic 标准化字段"""
        from ..schemas import HKSCHoldingsSchema
        from pydantic import ValidationError
        
        data = raw_data.get("data", {})
        
        try:
            schema = HKSCHoldingsSchema.from_raw_data(data)
            return schema.model_dump()
        except ValidationError as e:
            logger.error(f"HKSC holdings data validation failed: {e}")
            raise ServiceError(f"Invalid HKSC data: {e}")


class FundHoldingsAdapter(BaseServiceAdapter):
    """基金理财持仓服务适配器"""
    
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
    """现金资产服务适配器"""
    
    def _normalize_response(
        self,
        raw_data: dict[str, Any],
        account_type: str,
    ) -> dict[str, Any]:
        """使用 Pydantic 标准化字段"""
        from ..schemas import CashAssetsSchema
        from pydantic import ValidationError
        
        data = raw_data.get("data", {})
        
        try:
            schema = CashAssetsSchema.from_raw_data(data)
            return schema.model_dump()
        except ValidationError as e:
            logger.error(f"Cash assets data validation failed: {e}")
            raise ServiceError(f"Invalid cash data: {e}")


class SecurityDetailAdapter(BaseServiceAdapter):
    """具体标的详情服务适配器"""
    
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


def create_service_adapter(
    service_name: str,
    mock: bool = False,
) -> BaseServiceAdapter:
    """创建服务适配器
    
    Args:
        service_name: 服务名称（account_overview, etf_holdings等）
        mock: 是否使用 Mock 模式
    
    Returns:
        服务适配器实例
    """
    if mock:
        # 返回文件驱动的 Mock 适配器
        return MockServiceAdapter(service_name)
    
    # 从环境变量读取配置
    url = os.getenv(f"SECURITIES_{service_name.upper()}_URL")
    auth_type = os.getenv(f"SECURITIES_{service_name.upper()}_AUTH_TYPE", "header")
    auth_key = os.getenv(f"SECURITIES_{service_name.upper()}_AUTH_KEY", "Authorization")
    auth_value = os.getenv(f"SECURITIES_{service_name.upper()}_AUTH_VALUE")
    
    if not url:
        raise ValueError(f"Missing environment variable: SECURITIES_{service_name.upper()}_URL")
    
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
    }
    
    adapter_class = adapter_map.get(service_name)
    if adapter_class:
        return adapter_class(config)
    
    raise ValueError(f"Unknown service: {service_name}")
