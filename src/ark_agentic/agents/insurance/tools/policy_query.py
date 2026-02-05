"""
保单查询工具

查询用户的保单信息，包括保单列表、详情、现金价值等。
"""

from __future__ import annotations

from typing import Any

from ark_agentic.core.tools.base import (
    AgentTool,
    ToolParameter,
    read_string_param,
    read_string_param_required,
)
from ark_agentic.core.types import AgentToolResult, ToolCall


class PolicyQueryTool(AgentTool):
    """保单查询工具

    查询用户的保单信息。
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

    async def execute(
        self, tool_call: ToolCall, context: dict[str, Any] | None = None
    ) -> AgentToolResult:
        """执行保单查询"""
        args = tool_call.arguments
        user_id = read_string_param_required(args, "user_id")
        query_type = read_string_param_required(args, "query_type")
        policy_id = read_string_param(args, "policy_id")

        # 模拟查询逻辑
        # 实际实现中应调用后端服务
        if query_type == "list":
            result = self._query_policy_list(user_id)
        elif query_type == "detail":
            if not policy_id:
                return AgentToolResult.error_result(
                    tool_call.id, "查询保单详情需要提供 policy_id"
                )
            result = self._query_policy_detail(user_id, policy_id)
        elif query_type == "cash_value":
            if not policy_id:
                return AgentToolResult.error_result(
                    tool_call.id, "查询现金价值需要提供 policy_id"
                )
            result = self._query_cash_value(user_id, policy_id)
        elif query_type == "withdrawal_limit":
            result = self._query_withdrawal_limit(user_id, policy_id)
        else:
            return AgentToolResult.error_result(
                tool_call.id, f"不支持的查询类型: {query_type}"
            )

        return AgentToolResult.json_result(tool_call.id, result)

    def _query_policy_list(self, user_id: str) -> dict[str, Any]:
        """查询保单列表（模拟数据）"""
        return {
            "user_id": user_id,
            "policies": [
                {
                    "policy_id": "POL001",
                    "product_name": "平安福终身寿险",
                    "status": "active",
                    "premium": 12000,
                    "payment_years": 20,
                    "paid_years": 5,
                    "sum_insured": 500000,
                },
                {
                    "policy_id": "POL002",
                    "product_name": "金瑞人生年金险",
                    "status": "active",
                    "premium": 50000,
                    "payment_years": 5,
                    "paid_years": 3,
                    "sum_insured": 0,
                    "account_value": 168000,
                },
            ],
            "total_count": 2,
        }

    def _query_policy_detail(self, user_id: str, policy_id: str) -> dict[str, Any]:
        """查询保单详情（模拟数据）"""
        # 模拟数据
        if policy_id == "POL001":
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
                "loan_available": 33600,
                "riders": [
                    {"name": "重疾险", "sum_insured": 300000},
                    {"name": "意外险", "sum_insured": 100000},
                ],
            }
        elif policy_id == "POL002":
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
                "withdrawal_available": 65000,
                "surrender_value": 160000,
            }
        else:
            return {"error": f"保单 {policy_id} 不存在"}

    def _query_cash_value(self, user_id: str, policy_id: str) -> dict[str, Any]:
        """查询现金价值（模拟数据）"""
        if policy_id == "POL001":
            return {
                "policy_id": "POL001",
                "cash_value": 42000,
                "loan_rate": 0.8,
                "loan_available": 33600,
                "loan_interest_rate": 0.055,
            }
        elif policy_id == "POL002":
            return {
                "policy_id": "POL002",
                "account_value": 168000,
                "cash_value": 165000,
                "withdrawal_available": 65000,
                "withdrawal_fee_rate": 0,
            }
        else:
            return {"error": f"保单 {policy_id} 不存在"}

    def _query_withdrawal_limit(
        self, user_id: str, policy_id: str | None
    ) -> dict[str, Any]:
        """查询可取款额度（模拟数据）"""
        return {
            "user_id": user_id,
            "total_withdrawal_available": 98600,
            "details": [
                {
                    "policy_id": "POL001",
                    "type": "loan",
                    "available": 33600,
                    "description": "保单贷款（现金价值80%）",
                },
                {
                    "policy_id": "POL002",
                    "type": "partial_withdrawal",
                    "available": 65000,
                    "description": "部分领取（账户价值-保底金额）",
                },
            ],
        }
