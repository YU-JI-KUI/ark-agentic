"""
客户信息工具

查询客户的完整信息，包括身份、联系方式、受益人、历史交易等。
"""

from __future__ import annotations

from typing import Any

from ark_agentic.core.tools.base import (
    AgentTool,
    ToolParameter,
    read_string_param_required,
    read_string_param,
)
from ark_agentic.core.types import AgentToolResult, ToolCall


class CustomerInfoTool(AgentTool):
    """客户信息查询工具

    查询客户的详细信息，用于身份验证和业务办理。
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

    async def execute(
        self, tool_call: ToolCall, context: dict[str, Any] | None = None
    ) -> AgentToolResult:
        """执行客户信息查询"""
        args = tool_call.arguments
        user_id = read_string_param_required(args, "user_id")
        info_type = read_string_param_required(args, "info_type")
        policy_id = read_string_param(args, "policy_id")

        # 模拟查询
        if info_type == "identity":
            result = self._get_identity(user_id)
        elif info_type == "contact":
            result = self._get_contact(user_id)
        elif info_type == "beneficiary":
            result = self._get_beneficiary(user_id, policy_id)
        elif info_type == "transaction_history":
            result = self._get_transaction_history(user_id)
        elif info_type == "service_history":
            result = self._get_service_history(user_id)
        elif info_type == "full":
            result = self._get_full_info(user_id)
        else:
            return AgentToolResult.error_result(
                tool_call.id, f"不支持的查询类型: {info_type}"
            )

        return AgentToolResult.json_result(tool_call.id, result)

    def _get_identity(self, user_id: str) -> dict[str, Any]:
        """获取身份信息（模拟数据）"""
        return {
            "user_id": user_id,
            "identity": {
                "name": "张明",
                "id_type": "身份证",
                "id_number": "310***********1234",  # 脱敏
                "gender": "男",
                "birth_date": "1982-05-15",
                "age": 42,
                "verified": True,
                "verification_date": "2024-01-15",
            },
        }

    def _get_contact(self, user_id: str) -> dict[str, Any]:
        """获取联系方式（模拟数据）"""
        return {
            "user_id": user_id,
            "contact": {
                "phone": "138****5678",  # 脱敏
                "email": "zhang***@example.com",
                "address": "上海市浦东新区***路***号",
                "preferred_contact": "phone",
                "contact_time_preference": "工作日 9:00-18:00",
            },
        }

    def _get_beneficiary(
        self, user_id: str, policy_id: str | None
    ) -> dict[str, Any]:
        """获取受益人信息（模拟数据）"""
        beneficiaries = [
            {
                "policy_id": "POL001",
                "beneficiaries": [
                    {
                        "name": "张小明",
                        "relationship": "子女",
                        "id_number": "310***********5678",
                        "share": 0.5,
                        "order": 1,
                    },
                    {
                        "name": "李芳",
                        "relationship": "配偶",
                        "id_number": "310***********9012",
                        "share": 0.5,
                        "order": 1,
                    },
                ],
            },
            {
                "policy_id": "POL002",
                "beneficiaries": [
                    {
                        "name": "法定继承人",
                        "relationship": "法定",
                        "share": 1.0,
                        "order": 1,
                    },
                ],
            },
        ]

        if policy_id:
            for b in beneficiaries:
                if b["policy_id"] == policy_id:
                    return {"user_id": user_id, **b}
            return {"user_id": user_id, "error": f"未找到保单 {policy_id}"}

        return {"user_id": user_id, "beneficiaries_by_policy": beneficiaries}

    def _get_transaction_history(self, user_id: str) -> dict[str, Any]:
        """获取交易历史（模拟数据）"""
        return {
            "user_id": user_id,
            "transactions": [
                {
                    "id": "TXN001",
                    "date": "2024-06-15",
                    "type": "premium_payment",
                    "policy_id": "POL001",
                    "amount": 12000,
                    "status": "completed",
                    "description": "年度保费缴纳",
                },
                {
                    "id": "TXN002",
                    "date": "2024-03-20",
                    "type": "partial_withdrawal",
                    "policy_id": "POL002",
                    "amount": -30000,
                    "status": "completed",
                    "description": "部分领取",
                },
                {
                    "id": "TXN003",
                    "date": "2023-12-01",
                    "type": "premium_payment",
                    "policy_id": "POL002",
                    "amount": 50000,
                    "status": "completed",
                    "description": "年度保费缴纳",
                },
            ],
            "summary": {
                "total_premium_paid": 212000,
                "total_withdrawals": 30000,
                "last_transaction_date": "2024-06-15",
            },
        }

    def _get_service_history(self, user_id: str) -> dict[str, Any]:
        """获取服务记录（模拟数据）"""
        return {
            "user_id": user_id,
            "service_records": [
                {
                    "id": "SVC001",
                    "date": "2024-07-20",
                    "type": "inquiry",
                    "channel": "app",
                    "summary": "咨询取款方案",
                    "status": "resolved",
                },
                {
                    "id": "SVC002",
                    "date": "2024-03-15",
                    "type": "withdrawal",
                    "channel": "app",
                    "summary": "办理部分领取",
                    "status": "completed",
                },
                {
                    "id": "SVC003",
                    "date": "2023-11-10",
                    "type": "inquiry",
                    "channel": "phone",
                    "summary": "咨询保单权益",
                    "status": "resolved",
                },
            ],
            "statistics": {
                "total_interactions": 12,
                "app_interactions": 8,
                "phone_interactions": 4,
                "avg_satisfaction_score": 4.8,
            },
        }

    def _get_full_info(self, user_id: str) -> dict[str, Any]:
        """获取完整信息（模拟数据）"""
        return {
            "user_id": user_id,
            **self._get_identity(user_id),
            **self._get_contact(user_id),
            "beneficiaries_by_policy": self._get_beneficiary(user_id, None)[
                "beneficiaries_by_policy"
            ],
            "recent_transactions": self._get_transaction_history(user_id)[
                "transactions"
            ][:3],
            "recent_services": self._get_service_history(user_id)["service_records"][
                :3
            ],
        }


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
