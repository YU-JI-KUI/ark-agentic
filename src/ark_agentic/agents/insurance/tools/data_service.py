"""
数据服务客户端

统一管理 policy_query / customer_info 两个 API 的认证和调用。
两个 API 共享同一个 base URL，通过 apiCode 区分。
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class DataServiceClient:
    """保险数据服务客户端

    职责:
      - OAuth token 获取与缓存（5 分钟有效期）
      - 统一的 form-urlencoded POST 调用
      - 响应解析（data.Data JSON 嵌套）

    两个 API 使用方式:
        client = DataServiceClient()
        result = await client.call("policy_query", user_id="U001")
        result = await client.call("customer_info", user_id="U001")
    """

    # apiCode 常量
    API_POLICY_QUERY = "policy_query"
    API_CUSTOMER_INFO = "customer_info"

    def __init__(
        self,
        service_url: str | None = None,
        auth_url: str | None = None,
        app_id: str | None = None,
        client_type: str | None = None,
        req_channel: str | None = None,
        auth_client_id: str | None = None,
        auth_client_secret: str | None = None,
        auth_grant_type: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._service_url = service_url or os.getenv("DATA_SERVICE_URL", "")
        self._auth_url = auth_url or os.getenv("DATA_SERVICE_AUTH_URL", "")
        self._app_id = app_id or os.getenv("DATA_SERVICE_APP_ID", "")
        self._client_type = client_type or os.getenv("DATA_SERVICE_CLIENT_TYPE", "")
        self._req_channel = req_channel or os.getenv("DATA_SERVICE_REQ_CHANNEL", "")
        self._auth_client_id = auth_client_id or os.getenv("DATA_SERVICE_CLIENT_ID", "")
        self._auth_client_secret = auth_client_secret or os.getenv("DATA_SERVICE_CLIENT_SECRET", "")
        self._auth_grant_type = auth_grant_type or os.getenv("DATA_SERVICE_GRANT_TYPE", "client_credentials")
        self._timeout = timeout

        # token 缓存
        self._access_token: str = ""
        self._token_expires_at: float = 0.0

        # HTTP 客户端（惰性创建）
        self._http: httpx.AsyncClient | None = None

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    async def call(
        self,
        api_code: str,
        user_id: str,
        **extra_params: Any,
    ) -> dict[str, Any]:
        """调用数据服务 API

        Args:
            api_code: API 标识，"policy_query" 或 "customer_info"
            user_id: 用户 ID（写入 header userId）
            **extra_params: 额外的 form 参数

        Returns:
            解析后的业务数据字典

        Raises:
            DataServiceError: 调用失败
        """
        token = await self._ensure_token()
        client = await self._get_http()

        # headers
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "userId": user_id,
        }

        # form params
        form_data: dict[str, str] = {
            "appId": self._app_id,
            "clientType": self._client_type,
            "request_id": uuid.uuid4().hex,
            "access_token": token,
            "apiCode": api_code,
            "reqChannel": self._req_channel,
        }
        form_data.update({k: str(v) for k, v in extra_params.items()})

        logger.debug(f"DataService call: apiCode={api_code}, userId={user_id}")

        try:
            resp = await client.post(
                self._service_url,
                data=form_data,
                headers=headers,
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise DataServiceError(
                f"HTTP {exc.response.status_code}: {exc.response.text[:300]}"
            ) from exc
        except httpx.RequestError as exc:
            raise DataServiceError(f"Request failed: {exc}") from exc

        return self._parse_response(resp)

    async def close(self) -> None:
        if self._http and not self._http.is_closed:
            await self._http.aclose()
            self._http = None

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    async def _get_http(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout, connect=10.0),
            )
        return self._http

    async def _ensure_token(self) -> str:
        """获取有效 token，过期则重新获取。预留 30 秒安全余量。"""
        if self._access_token and time.time() < self._token_expires_at - 30:
            return self._access_token

        self._access_token, expires_in = await self._fetch_token()
        self._token_expires_at = time.time() + expires_in
        logger.info(f"DataService token refreshed, expires_in={expires_in}s")
        return self._access_token

    async def _fetch_token(self) -> tuple[str, int]:
        """调用 auth URL 获取 access_token

        Returns:
            (access_token, expires_in_seconds)
        """
        if not self._auth_url:
            raise DataServiceError("DATA_SERVICE_AUTH_URL not configured")

        client = await self._get_http()
        body = {
            "client_id": self._auth_client_id,
            "client_secret": self._auth_client_secret,
            "grant_type": self._auth_grant_type,
        }

        try:
            resp = await client.get(self._auth_url, params=body)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise DataServiceError(
                f"Auth HTTP {exc.response.status_code}: {exc.response.text[:300]}"
            ) from exc
        except httpx.RequestError as exc:
            raise DataServiceError(f"Auth request failed: {exc}") from exc

        data = resp.json()
        # 结构: {ret, msg, data: {access_token, expires_in, openid}}
        if data.get("ret") != 0 and data.get("ret") != "0":
            raise DataServiceError(f"Auth failed: ret={data.get('ret')}, msg={data.get('msg')}")

        token_data = data.get("data", {})
        access_token = token_data.get("access_token", "")
        expires_in = int(token_data.get("expires_in", 300))

        if not access_token:
            raise DataServiceError("Auth returned empty access_token")

        return access_token, expires_in

    @staticmethod
    def _parse_response(resp: httpx.Response) -> dict[str, Any]:
        """解析数据服务响应

        响应结构: HTTP body 是 JSON string，其中 data.Data 是业务数据（也是 JSON string）
        """
        try:
            outer = resp.json()
        except (json.JSONDecodeError, ValueError):
            # 尝试 text 解析
            outer = json.loads(resp.text)

        # 提取 data.Data
        data_field = outer.get("data", {})
        if isinstance(data_field, str):
            data_field = json.loads(data_field)

        inner_data = data_field.get("Data", data_field.get("data"))
        if isinstance(inner_data, str):
            try:
                return json.loads(inner_data)
            except (json.JSONDecodeError, ValueError):
                return {"raw": inner_data}

        if isinstance(inner_data, dict):
            return inner_data

        # fallback: 返回整个 outer
        return outer


class DataServiceError(Exception):
    """数据服务调用异常"""


# ==================================================================
# Mock 客户端 — 开发/测试用，通过 DATA_SERVICE_MOCK=true 启用
# ==================================================================


class MockDataServiceClient:
    """Mock 数据服务客户端

    实现与 DataServiceClient 相同的 call() 接口，返回硬编码测试数据。
    无需网络连接和认证。
    """

    API_POLICY_QUERY = DataServiceClient.API_POLICY_QUERY
    API_CUSTOMER_INFO = DataServiceClient.API_CUSTOMER_INFO

    async def call(
        self,
        api_code: str,
        user_id: str,
        **extra_params: Any,
    ) -> dict[str, Any]:
        logger.debug(f"MockDataService call: apiCode={api_code}, userId={user_id}, params={extra_params}")

        if api_code == self.API_POLICY_QUERY:
            return self._mock_policy_query(user_id, extra_params)
        if api_code == self.API_CUSTOMER_INFO:
            return self._mock_customer_info(user_id, extra_params)

        return {"error": f"Unknown apiCode: {api_code}"}

    async def close(self) -> None:
        pass

    # ------ policy_query mock ------

    @staticmethod
    def _mock_policy_query(user_id: str, params: dict[str, Any]) -> dict[str, Any]:
        qt = params.get("query_type", "list")
        pid = params.get("policy_id")

        if qt == "list":
            return {
                "user_id": user_id,
                "policyAssertList": [
                    {
                        "policy_id": "POL001",
                        "product_name": "平安福终身寿险",
                        "product_type": "whole_life",
                        "status": "active",
                        "effective_date": "2019-03-15",
                        "premium": 12000,
                        "payment_years": 20,
                        "paid_years": 5,
                        "sum_insured": 500000,
                        "account_value": 0,
                        "bounusAmt": 0,
                        "loanAmt": 33600,
                        "survivalFundAmt": 0,
                        "policyRefundAmount": 42000,
                    },
                    {
                        "policy_id": "POL002",
                        "product_name": "金瑞人生年金险",
                        "product_type": "annuity",
                        "status": "active",
                        "effective_date": "2021-06-01",
                        "premium": 50000,
                        "payment_years": 5,
                        "paid_years": 3,
                        "sum_insured": 0,
                        "account_value": 168000,
                        "bounusAmt": 5200,
                        "loanAmt": 0,
                        "survivalFundAmt": 12000,
                        "policyRefundAmount": 160000,
                    },
                    {
                        "policy_id": "POL003",
                        "product_name": "智盈人生万能险",
                        "product_type": "universal_life",
                        "status": "active",
                        "effective_date": "2022-09-01",
                        "premium": 30000,
                        "payment_years": 10,
                        "paid_years": 3,
                        "sum_insured": 200000,
                        "account_value": 95000,
                        "bounusAmt": 0,
                        "loanAmt": 0,
                        "survivalFundAmt": 0,
                        "policyRefundAmount": 85000,
                    },
                ],
                "total_count": 3,
            }

        if qt == "detail":
            if pid == "POL001":
                return {
                    "policy_id": "POL001",
                    "product_name": "平安福终身寿险",
                    "product_type": "whole_life",
                    "status": "active",
                    "effective_date": "2019-03-15",
                    "premium": 12000,
                    "payment_frequency": "annual",
                    "payment_years": 20,
                    "paid_years": 5,
                    "sum_insured": 500000,
                    "cash_value": 42000,
                    "bounusAmt": 0,
                    "loanAmt": 33600,
                    "survivalFundAmt": 0,
                    "policyRefundAmount": 42000,
                    "riders": [
                        {"name": "重疾险", "sum_insured": 300000},
                        {"name": "意外险", "sum_insured": 100000},
                    ],
                }
            if pid == "POL002":
                return {
                    "policy_id": "POL002",
                    "product_name": "金瑞人生年金险",
                    "product_type": "annuity",
                    "status": "active",
                    "effective_date": "2021-06-01",
                    "premium": 50000,
                    "payment_frequency": "annual",
                    "payment_years": 5,
                    "paid_years": 3,
                    "account_value": 168000,
                    "cash_value": 165000,
                    "bounusAmt": 5200,
                    "loanAmt": 0,
                    "survivalFundAmt": 12000,
                    "policyRefundAmount": 160000,
                }
            if pid == "POL003":
                return {
                    "policy_id": "POL003",
                    "product_name": "智盈人生万能险",
                    "product_type": "universal_life",
                    "status": "active",
                    "effective_date": "2022-09-01",
                    "premium": 30000,
                    "payment_frequency": "annual",
                    "payment_years": 10,
                    "paid_years": 3,
                    "sum_insured": 200000,
                    "account_value": 95000,
                    "cash_value": 88000,
                    "bounusAmt": 0,
                    "loanAmt": 0,
                    "survivalFundAmt": 0,
                    "policyRefundAmount": 85000,
                }
            return {"error": f"保单 {pid} 不存在"}

        if qt == "cash_value":
            if pid == "POL001":
                return {
                    "policy_id": "POL001",
                    "cash_value": 42000,
                    "loan_rate": 0.8,
                    "bounusAmt": 0,
                    "loanAmt": 33600,
                    "survivalFundAmt": 0,
                    "policyRefundAmount": 42000,
                }
            if pid == "POL002":
                return {
                    "policy_id": "POL002",
                    "account_value": 168000,
                    "cash_value": 165000,
                    "bounusAmt": 5200,
                    "loanAmt": 0,
                    "survivalFundAmt": 12000,
                    "policyRefundAmount": 160000,
                }
            if pid == "POL003":
                return {
                    "policy_id": "POL003",
                    "account_value": 95000,
                    "cash_value": 88000,
                    "bounusAmt": 0,
                    "loanAmt": 0,
                    "survivalFundAmt": 0,
                    "policyRefundAmount": 85000,
                }
            return {"error": f"保单 {pid} 不存在"}

        if qt == "withdrawal_limit":
            # 汇总各保单可用的取款渠道，与 list 中的四个金额字段一致
            return {
                "user_id": user_id,
                "total_withdrawal_available": 337800,
                "details": [
                    {
                        "policy_id": "POL001",
                        "type": "loan",
                        "available": 33600,
                        "source_field": "loanAmt",
                        "description": "保单贷款",
                    },
                    {
                        "policy_id": "POL001",
                        "type": "surrender",
                        "available": 42000,
                        "source_field": "policyRefundAmount",
                        "description": "退保",
                    },
                    {
                        "policy_id": "POL002",
                        "type": "survival_fund",
                        "available": 12000,
                        "source_field": "survivalFundAmt",
                        "description": "生存金领取",
                    },
                    {
                        "policy_id": "POL002",
                        "type": "bonus",
                        "available": 5200,
                        "source_field": "bounusAmt",
                        "description": "红利领取",
                    },
                    {
                        "policy_id": "POL002",
                        "type": "partial_withdrawal",
                        "available": 160000,
                        "source_field": "policyRefundAmount",
                        "description": "部分领取",
                    },
                    {
                        "policy_id": "POL003",
                        "type": "partial_withdrawal",
                        "available": 85000,
                        "source_field": "policyRefundAmount",
                        "description": "万能险部分领取",
                    },
                ],
            }

        return {"error": f"不支持的查询类型: {qt}"}

    # ------ customer_info mock ------

    @staticmethod
    def _mock_customer_info(user_id: str, params: dict[str, Any]) -> dict[str, Any]:
        it = params.get("info_type", "full")
        pid = params.get("policy_id")

        identity = {
            "name": "张明",
            "id_type": "身份证",
            "id_number": "310***********1234",
            "gender": "男",
            "birth_date": "1982-05-15",
            "age": 42,
            "has_children": True,
            "marital_status": "已婚",
            "verified": True,
            "verification_date": "2024-01-15",
        }
        contact = {
            "phone": "138****5678",
            "email": "zhang***@example.com",
            "address": "上海市浦东新区***路***号",
            "preferred_contact": "phone",
            "contact_time_preference": "工作日 9:00-18:00",
        }
        beneficiaries = [
            {
                "policy_id": "POL001",
                "beneficiaries": [
                    {"name": "张小明", "relationship": "子女", "id_number": "310***********5678", "share": 0.5, "order": 1},
                    {"name": "李芳", "relationship": "配偶", "id_number": "310***********9012", "share": 0.5, "order": 1},
                ],
            },
            {
                "policy_id": "POL002",
                "beneficiaries": [{"name": "法定继承人", "relationship": "法定", "share": 1.0, "order": 1}],
            },
            {
                "policy_id": "POL003",
                "beneficiaries": [{"name": "法定继承人", "relationship": "法定", "share": 1.0, "order": 1}],
            },
        ]
        transactions = [
            {
                "id": "TXN001", "date": "2024-06-15", "type": "premium_payment",
                "policy_id": "POL001", "amount": 12000, "status": "completed",
                "description": "年度保费缴纳"
            },
            {
                "id": "TXN002", "date": "2024-03-20", "type": "partial_withdrawal",
                "policy_id": "POL002", "amount": -30000, "status": "completed",
                "description": "部分领取"
            },
            {
                "id": "TXN003", "date": "2023-12-01", "type": "premium_payment",
                "policy_id": "POL002", "amount": 50000, "status": "completed",
                "description": "年度保费缴纳"
            },
        ]
        service_records = [
            {
                "id": "SVC001", "date": "2024-07-20", "type": "inquiry",
                "channel": "app", "summary": "咨询取款方案", "status": "resolved"
            },
            {
                "id": "SVC002", "date": "2024-03-15", "type": "withdrawal",
                "channel": "app", "summary": "办理部分领取", "status": "completed"
            },
            {
                "id": "SVC003", "date": "2023-11-10", "type": "inquiry",
                "channel": "phone", "summary": "咨询保单权益", "status": "resolved"
            },
        ]

        if it == "identity":
            return {"user_id": user_id, "identity": identity}
        if it == "contact":
            return {"user_id": user_id, "contact": contact}
        if it == "beneficiary":
            if pid:
                for b in beneficiaries:
                    if b["policy_id"] == pid:
                        return {"user_id": user_id, **b}
                return {"user_id": user_id, "error": f"未找到保单 {pid}"}
            return {"user_id": user_id, "beneficiaries_by_policy": beneficiaries}
        if it == "transaction_history":
            return {
                "user_id": user_id,
                "transactions": transactions,
                "summary": {
                    "total_premium_paid": 212000,
                    "total_withdrawals": 30000,
                    "last_transaction_date": "2024-06-15"
                },
            }
        if it == "service_history":
            return {
                "user_id": user_id,
                "service_records": service_records,
                "statistics": {
                    "total_interactions": 12,
                    "app_interactions": 8,
                    "phone_interactions": 4,
                    "avg_satisfaction_score": 4.8
                },
            }
        # full
        return {
            "user_id": user_id,
            "identity": identity,
            "contact": contact,
            "beneficiaries_by_policy": beneficiaries,
            "recent_transactions": transactions[:3],
            "recent_services": service_records[:3],
        }


# ------------------------------------------------------------------
# 单例管理
# ------------------------------------------------------------------

_default_client: DataServiceClient | MockDataServiceClient | None = None


def get_data_service_client() -> DataServiceClient | MockDataServiceClient:
    """获取全局数据服务客户端单例

    当 DATA_SERVICE_MOCK=true 时返回 MockDataServiceClient，否则返回真实客户端。
    """
    global _default_client
    if _default_client is None:
        if os.getenv("DATA_SERVICE_MOCK", "").lower() in ("true", "1", "yes"):
            logger.info("Using MockDataServiceClient (DATA_SERVICE_MOCK=true)")
            _default_client = MockDataServiceClient()
        else:
            _default_client = DataServiceClient()
    return _default_client


def reset_data_service_client() -> None:
    """重置单例（用于测试切换 mock/real）"""
    global _default_client
    _default_client = None
