"""
规则引擎工具

根据业务规则计算取款方案、费用、影响等。
"""

from __future__ import annotations

from typing import Any

from ark_agentic.core.tools.base import (
    AgentTool,
    ToolParameter,
    read_string_param_required,
    read_float_param,
    read_dict_param,
)
from ark_agentic.core.types import AgentToolResult, ToolCall


class RuleEngineTool(AgentTool):
    """规则引擎工具

    根据业务规则计算取款方案。
    """

    name = "rule_engine"
    description = "根据业务规则计算取款方案，包括可取金额、费用、对保障的影响等"
    group = "insurance"

    parameters = [
        ToolParameter(
            name="action",
            type="string",
            description="操作类型",
            required=True,
            enum=["calculate_withdrawal", "calculate_loan", "calculate_surrender", "compare_plans"],
        ),
        ToolParameter(
            name="policy_id",
            type="string",
            description="保单ID",
            required=True,
        ),
        ToolParameter(
            name="amount",
            type="number",
            description="期望金额（可选，不提供则计算最大可取）",
            required=False,
        ),
        ToolParameter(
            name="policy_data",
            type="object",
            description="保单数据（从 policy_query 获取）",
            required=False,
        ),
    ]

    async def execute(
        self, tool_call: ToolCall, context: dict[str, Any] | None = None
    ) -> AgentToolResult:
        """执行规则计算"""
        args = tool_call.arguments
        action = read_string_param_required(args, "action")
        policy_id = read_string_param_required(args, "policy_id")
        amount = read_float_param(args, "amount")
        policy_data = read_dict_param(args, "policy_data") or {}

        if action == "calculate_withdrawal":
            result = self._calculate_withdrawal(policy_id, amount, policy_data)
        elif action == "calculate_loan":
            result = self._calculate_loan(policy_id, amount, policy_data)
        elif action == "calculate_surrender":
            result = self._calculate_surrender(policy_id, policy_data)
        elif action == "compare_plans":
            result = self._compare_plans(policy_id, amount, policy_data)
        else:
            return AgentToolResult.error_result(
                tool_call.id, f"不支持的操作: {action}"
            )

        return AgentToolResult.json_result(tool_call.id, result)

    def _calculate_withdrawal(
        self, policy_id: str, amount: float | None, policy_data: dict[str, Any]
    ) -> dict[str, Any]:
        """计算部分领取方案"""
        # 模拟计算逻辑
        max_available = 65000  # 从保单数据获取

        if amount and amount > max_available:
            return {
                "success": False,
                "error": f"请求金额 {amount} 超过可领取上限 {max_available}",
                "max_available": max_available,
            }

        actual_amount = amount or max_available

        return {
            "success": True,
            "policy_id": policy_id,
            "plan_type": "partial_withdrawal",
            "plan_name": "部分领取",
            "requested_amount": amount,
            "actual_amount": actual_amount,
            "fee": 0,
            "net_amount": actual_amount,
            "processing_time": "3-5个工作日",
            "impact": {
                "account_value_change": -actual_amount,
                "cash_value_change": -actual_amount * 0.98,
                "coverage_impact": "无影响",
                "future_benefit_impact": "年金领取金额相应减少",
            },
            "requirements": [
                "投保满2年",
                "账户价值大于保底金额",
            ],
            "notes": [
                "部分领取不收取手续费",
                "领取后账户价值相应减少",
                "每年最多领取2次",
            ],
        }

    def _calculate_loan(
        self, policy_id: str, amount: float | None, policy_data: dict[str, Any]
    ) -> dict[str, Any]:
        """计算保单贷款方案"""
        max_available = 33600  # 现金价值的80%
        interest_rate = 0.055  # 年利率5.5%

        if amount and amount > max_available:
            return {
                "success": False,
                "error": f"请求金额 {amount} 超过可贷款上限 {max_available}",
                "max_available": max_available,
            }

        actual_amount = amount or max_available

        return {
            "success": True,
            "policy_id": policy_id,
            "plan_type": "policy_loan",
            "plan_name": "保单贷款",
            "requested_amount": amount,
            "actual_amount": actual_amount,
            "fee": 0,
            "net_amount": actual_amount,
            "interest_rate": interest_rate,
            "interest_annual": actual_amount * interest_rate,
            "processing_time": "1-2个工作日",
            "repayment_term": "6个月一周期，可续贷",
            "impact": {
                "coverage_impact": "保障不变",
                "cash_value_impact": "贷款期间现金价值仍按原利率增长",
                "risk": "若未按时还款，利息计入本金复利计算",
            },
            "requirements": [
                "保单生效满1年",
                "保单状态正常",
            ],
            "notes": [
                "保单贷款不影响保障",
                "贷款利息按日计算",
                "可随时部分或全部还款",
            ],
        }

    def _calculate_surrender(
        self, policy_id: str, policy_data: dict[str, Any]
    ) -> dict[str, Any]:
        """计算退保方案"""
        surrender_value = 160000

        return {
            "success": True,
            "policy_id": policy_id,
            "plan_type": "surrender",
            "plan_name": "退保",
            "surrender_value": surrender_value,
            "total_premium_paid": 150000,
            "surrender_loss": -10000,
            "processing_time": "5-7个工作日",
            "impact": {
                "coverage_impact": "所有保障终止",
                "warning": "退保后无法恢复，请谨慎考虑",
            },
            "notes": [
                "退保将失去所有保障",
                "退保金额低于已交保费",
                "建议优先考虑其他方式取款",
            ],
        }

    def _compare_plans(
        self, policy_id: str, amount: float | None, policy_data: dict[str, Any]
    ) -> dict[str, Any]:
        """比较多种方案"""
        withdrawal = self._calculate_withdrawal(policy_id, amount, policy_data)
        loan = self._calculate_loan(policy_id, amount, policy_data)
        surrender = self._calculate_surrender(policy_id, policy_data)

        return {
            "policy_id": policy_id,
            "requested_amount": amount,
            "plans": [
                {
                    "rank": 1,
                    "plan": withdrawal,
                    "recommendation": "推荐" if withdrawal.get("success") else "不可用",
                    "reason": "不影响保障，无利息成本",
                },
                {
                    "rank": 2,
                    "plan": loan,
                    "recommendation": "可选" if loan.get("success") else "不可用",
                    "reason": "保障不变，但需支付利息",
                },
                {
                    "rank": 3,
                    "plan": surrender,
                    "recommendation": "不推荐",
                    "reason": "会失去所有保障，且可能有损失",
                },
            ],
            "summary": "建议优先选择部分领取，其次是保单贷款，退保作为最后选择",
        }
