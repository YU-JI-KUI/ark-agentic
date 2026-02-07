"""
保单查询工具

查询用户的保单信息，包括保单列表、详情、现金价值等。
通过数据服务 API（apiCode=policy_query）获取真实数据。
"""

from __future__ import annotations

import logging
from typing import Any

from ark_agentic.core.tools.base import (
    AgentTool,
    ToolParameter,
    read_string_param,
    read_string_param_required,
)
from ark_agentic.core.types import AgentToolResult, ToolCall

from .data_service import DataServiceClient, MockDataServiceClient, DataServiceError, get_data_service_client

logger = logging.getLogger(__name__)


class PolicyQueryTool(AgentTool):
    """保单查询工具

    通过数据服务 policy_query API 查询用户的保单信息。
    """

    name = "policy_query"
    description = "查询用户的保单信息，包括保单列表、保单详情、现金价值、可取款额度等"
    group = "insurance"

    parameters = [
        ToolParameter(
            name="user_id",
            type="string",
            description="用户ID",
            required=True,
        ),
        ToolParameter(
            name="query_type",
            type="string",
            description="查询类型",
            required=True,
            enum=["list", "detail", "cash_value", "withdrawal_limit"],
        ),
        ToolParameter(
            name="policy_id",
            type="string",
            description="保单ID（查询详情时必需）",
            required=False,
        ),
    ]

    def __init__(self, client: DataServiceClient | MockDataServiceClient | None = None) -> None:
        self._client = client or get_data_service_client()

    async def execute(
        self, tool_call: ToolCall, context: dict[str, Any] | None = None
    ) -> AgentToolResult:
        """执行保单查询"""
        args = tool_call.arguments
        user_id = read_string_param_required(args, "user_id")
        query_type = read_string_param_required(args, "query_type")
        policy_id = read_string_param(args, "policy_id")

        # 参数校验
        if query_type in ("detail", "cash_value") and not policy_id:
            return AgentToolResult.error_result(
                tool_call.id, f"查询{query_type}需要提供 policy_id"
            )

        extra: dict[str, str] = {"query_type": query_type}
        if policy_id:
            extra["policy_id"] = policy_id

        try:
            result = await self._client.call(
                api_code=DataServiceClient.API_POLICY_QUERY,
                user_id=user_id,
                **extra,
            )
        except DataServiceError as exc:
            logger.error(f"policy_query API error: {exc}")
            return AgentToolResult.error_result(tool_call.id, str(exc))

        return AgentToolResult.json_result(tool_call.id, result)
