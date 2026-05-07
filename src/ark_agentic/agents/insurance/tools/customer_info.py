"""
客户信息工具

查询客户的完整信息，包括身份、联系方式、受益人、历史交易等。
通过数据服务 API（apiCode=customer_info）获取真实数据。
"""

from __future__ import annotations

import logging
from typing import Any

from ark_agentic.core.tools.base import (
    AgentTool,
    ToolParameter,
    read_string_param_required,
    read_string_param,
)
from ark_agentic.core.types import AgentToolResult, ToolCall

from .data_service import DataServiceClient, MockDataServiceClient, DataServiceError, get_data_service_client

logger = logging.getLogger(__name__)


class CustomerInfoTool(AgentTool):
    """客户信息查询工具

    通过数据服务 customer_info API 查询客户详细信息。
    """

    name = "customer_info"
    description = "查询客户完整信息，包括身份验证、联系方式、受益人信息、历史交易记录等"
    thinking_hint = "正在查询客户信息…"
    group = "insurance"
    data_source = True

    parameters = [
        ToolParameter(
            name="user_id",
            type="string",
            description="用户ID",
            required=True,
        ),
        ToolParameter(
            name="info_type",
            type="string",
            description="查询类型",
            required=True,
            enum=[
                "identity",  # 身份信息
                "contact",  # 联系方式
                "beneficiary",  # 受益人信息
                "transaction_history",  # 交易历史
                "service_history",  # 服务记录
                "full",  # 完整信息
            ],
        ),
        ToolParameter(
            name="policy_id",
            type="string",
            description="保单ID（查询受益人时需要）",
            required=False,
        ),
    ]

    def __init__(self, client: DataServiceClient | MockDataServiceClient | None = None) -> None:
        self._client = client or get_data_service_client()

    async def execute(
        self, tool_call: ToolCall, context: dict[str, Any] | None = None
    ) -> AgentToolResult:
        """执行客户信息查询"""
        args = tool_call.arguments
        user_id = read_string_param_required(args, "user_id")
        info_type = read_string_param_required(args, "info_type")
        policy_id = read_string_param(args, "policy_id")

        extra: dict[str, str] = {"info_type": info_type}
        if policy_id:
            extra["policy_id"] = policy_id

        try:
            result = await self._client.call(
                api_code=DataServiceClient.API_CUSTOMER_INFO,
                user_id=user_id,
                **extra,
            )
        except DataServiceError as exc:
            logger.error(f"customer_info API error: {exc}")
            return AgentToolResult.error_result(tool_call.id, str(exc))

        metadata = {"state_delta": {"_customer_info_result": result}}
        return AgentToolResult.json_result(tool_call.id, result, metadata=metadata)
