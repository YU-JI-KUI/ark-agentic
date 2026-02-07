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
    group = "insurance"

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

        return AgentToolResult.json_result(tool_call.id, result)


class IdentityVerificationTool(AgentTool):
    """身份验证工具

    验证客户身份，用于敏感操作前的安全确认。
    """

    name = "verify_identity"
    description = "验证客户身份，支持多种验证方式（短信验证码、人脸识别等）"
    group = "insurance"

    parameters = [
        ToolParameter(
            name="user_id",
            type="string",
            description="用户ID",
            required=True,
        ),
        ToolParameter(
            name="verification_method",
            type="string",
            description="验证方式",
            required=True,
            enum=["sms", "face", "password", "question"],
        ),
        ToolParameter(
            name="verification_data",
            type="string",
            description="验证数据（如验证码）",
            required=False,
        ),
    ]

    async def execute(
        self, tool_call: ToolCall, context: dict[str, Any] | None = None
    ) -> AgentToolResult:
        """执行身份验证"""
        args = tool_call.arguments
        user_id = read_string_param_required(args, "user_id")
        method = read_string_param_required(args, "verification_method")
        data = read_string_param(args, "verification_data")

        # 模拟验证逻辑
        if method == "sms":
            if not data:
                # 发送验证码
                result = {
                    "status": "pending",
                    "message": "验证码已发送至手机 138****5678",
                    "expires_in": 300,
                    "hint": "请输入收到的6位验证码",
                }
            else:
                # 验证验证码
                if data == "123456":  # 模拟正确验证码
                    result = {
                        "status": "verified",
                        "message": "身份验证成功",
                        "verification_token": "VT_" + user_id + "_" + str(hash(data))[:8],
                        "valid_for": "30分钟",
                    }
                else:
                    result = {
                        "status": "failed",
                        "message": "验证码错误，请重新输入",
                        "remaining_attempts": 2,
                    }
        elif method == "face":
            result = {
                "status": "pending",
                "message": "请在APP中完成人脸识别验证",
                "redirect_url": "app://face_verify",
            }
        elif method == "password":
            result = {
                "status": "pending",
                "message": "请输入您的登录密码",
            }
        elif method == "question":
            result = {
                "status": "pending",
                "message": "请回答安全问题",
                "question": "您的第一辆车的品牌是什么？",
            }
        else:
            return AgentToolResult.error_result(
                tool_call.id, f"不支持的验证方式: {method}"
            )

        return AgentToolResult.json_result(
            tool_call.id, {"user_id": user_id, "method": method, **result}
        )
