"""
规则引擎工具

根据业务规则计算取款方案、费用、影响等。
基于保单数据中的四个金额字段进行确定性计算：
  - bounusAmt   红利
  - loanAmt     可贷款额度
  - survivalFundAmt  生存金 / 满期金
  - policyRefundAmount  退保金额（部分领取 / 全额退保）

compare_plans 通过 user_id 自行获取保单数据，无需 LLM 中转。
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

from ark_agentic.core.tools.base import (
    AgentTool,
    ToolParameter,
    read_string_param_required,
    read_string_param,
    read_float_param,
    read_dict_param,
)
from ark_agentic.core.types import AgentToolResult, ToolCall

from .data_service import (
    DataServiceClient,
    DataServiceError,
    MockDataServiceClient,
    get_data_service_client,
)

logger = logging.getLogger(__name__)


# ============ 业务规则常量 ============

# 保单贷款固定年利率
LOAN_INTEREST_RATE = 0.05

# 部分领取手续费率（按保单年度）
# 第1年 3%, 第2年 2%, 第3-5年 1%, 第6年起 0%
WITHDRAWAL_FEE_SCHEDULE: dict[int, float] = {
    1: 0.03,
    2: 0.02,
    3: 0.01,
    4: 0.01,
    5: 0.01,
}

# 统一到账时间
PROCESSING_TIME = "1-3个工作日"

# 优先级定义（数值越小优先级越高）
PRIORITY_SURVIVAL_FUND = 1    # 生存金 / 满期金
PRIORITY_BONUS = 1            # 红利领取
PRIORITY_UNIVERSAL_LIFE = 2   # 万能险部分领取
PRIORITY_WHOLE_LIFE = 3       # 终身寿险部分领取 / 退保
PRIORITY_POLICY_LOAN = 99     # 保单贷款（特殊级别，按场景推荐）

# 优先级中文标签
PRIORITY_LABELS = {
    1: "优先推荐",
    2: "可选",
    3: "谨慎推荐",
    99: "紧急周转适用",
}


# ============ 辅助函数 ============


def _compute_policy_year(effective_date: str) -> int:
    """根据保单生效日期计算当前处于第几个保单年度。

    Args:
        effective_date: 保单生效日期，格式 YYYY-MM-DD

    Returns:
        保单年度（从 1 开始），解析失败时默认返回 6（即无手续费）。
    """
    try:
        eff = datetime.strptime(effective_date, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        logger.warning(f"无法解析保单生效日期: {effective_date}，默认视为第6年度")
        return 6

    today = date.today()
    # 年度差 + 1，例如同年投保 = 第1年
    years = today.year - eff.year
    if (today.month, today.day) < (eff.month, eff.day):
        years -= 1
    return max(years + 1, 1)


def _get_fee_rate(policy_year: int) -> float:
    """根据保单年度返回部分领取手续费率。"""
    if policy_year >= 6:
        return 0.0
    return WITHDRAWAL_FEE_SCHEDULE.get(policy_year, 0.0)


# ============ 规则引擎工具 ============


class RuleEngineTool(AgentTool):
    """规则引擎工具

    compare_plans: 接收 user_id，内部获取保单数据，按优先级排序可用取款方案。
    calculate_detail: 接收单张保单数据，对某种方案做精确费用计算。
    """

    name = "rule_engine"
    description = (
        "根据业务规则计算取款方案。"
        "compare_plans 根据 user_id 自动获取保单数据并返回按优先级排序的可选方案；"
        "calculate_detail 对单张保单的某种方案做详细费用计算。"
    )
    group = "insurance"

    parameters = [
        ToolParameter(
            name="action",
            type="string",
            description="操作类型：compare_plans（方案比较）或 calculate_detail（单方案详算）",
            required=True,
            enum=["compare_plans", "calculate_detail"],
        ),
        ToolParameter(
            name="user_id",
            type="string",
            description="用户ID（compare_plans 时必填），规则引擎会自动查询该用户的保单数据",
            required=False,
        ),
        ToolParameter(
            name="policy",
            type="object",
            description="单张保单数据（calculate_detail 时必填），从 policy_query 返回的保单对象",
            required=False,
        ),
        ToolParameter(
            name="plan_type",
            type="string",
            description="方案类型（calculate_detail 时必填）",
            required=False,
            enum=["survival_fund", "bonus", "partial_withdrawal", "surrender", "policy_loan"],
        ),
        ToolParameter(
            name="amount",
            type="number",
            description="期望金额（可选，不提供则返回各方案最大可用额度）",
            required=False,
        ),
    ]

    def __init__(
        self, client: DataServiceClient | MockDataServiceClient | None = None
    ) -> None:
        self._client = client or get_data_service_client()

    async def execute(
        self, tool_call: ToolCall, context: dict[str, Any] | None = None
    ) -> AgentToolResult:
        """执行规则计算"""
        args = tool_call.arguments
        action = read_string_param_required(args, "action")

        if action == "compare_plans":
            user_id = read_string_param(args, "user_id")
            if not user_id:
                return AgentToolResult.error_result(
                    tool_call.id, "compare_plans 需要提供 user_id 参数"
                )
            amount = read_float_param(args, "amount")
            try:
                result = await self._compare_plans(user_id, amount)
            except DataServiceError as exc:
                logger.error(f"rule_engine compare_plans data fetch error: {exc}")
                return AgentToolResult.error_result(tool_call.id, f"获取保单数据失败: {exc}")

        elif action == "calculate_detail":
            policy = read_dict_param(args, "policy")
            if not policy:
                return AgentToolResult.error_result(
                    tool_call.id, "calculate_detail 需要提供 policy 参数（单张保单数据）"
                )
            plan_type = read_string_param(args, "plan_type")
            if not plan_type:
                return AgentToolResult.error_result(
                    tool_call.id, "calculate_detail 需要提供 plan_type 参数"
                )
            amount = read_float_param(args, "amount")
            result = self._calculate_detail(policy, plan_type, amount)

        else:
            return AgentToolResult.error_result(
                tool_call.id, f"不支持的操作: {action}"
            )

        return AgentToolResult.json_result(tool_call.id, result)

    # ------------------------------------------------------------------
    # compare_plans: 自动获取保单数据 → 方案比较
    # ------------------------------------------------------------------

    async def _compare_plans(
        self,
        user_id: str,
        amount: float | None,
    ) -> dict[str, Any]:
        """通过 user_id 获取保单列表，生成候选方案并按优先级排序。"""
        # 直接调用数据服务获取保单列表，避免 LLM 中转
        data = await self._client.call(
            api_code=DataServiceClient.API_POLICY_QUERY,
            user_id=user_id,
            query_type="list",
        )
        policies = data.get("policies", [])
        if not policies:
            return {
                "requested_amount": amount,
                "total_available_excl_loan": 0,
                "total_available_incl_loan": 0,
                "combination_hint": "未找到该用户的有效保单",
                "plans": [],
            }

        return self._build_plans(policies, amount)

    def _build_plans(
        self,
        policies: list[dict[str, Any]],
        amount: float | None,
    ) -> dict[str, Any]:
        """遍历所有保单，生成候选方案并按优先级排序。"""
        candidates: list[dict[str, Any]] = []

        for pol in policies:
            policy_id = pol.get("policy_id", "")
            product_name = pol.get("product_name", "")
            product_type = pol.get("product_type", "")
            effective_date = pol.get("effective_date", "")
            policy_year = _compute_policy_year(effective_date) if effective_date else 6

            # ---------- 生存金 / 满期金 ----------
            survival = float(pol.get("survivalFundAmt", 0) or 0)
            if survival > 0:
                candidates.append(self._make_plan(
                    policy_id=policy_id,
                    product_name=product_name,
                    plan_type="survival_fund",
                    plan_name="生存金领取",
                    priority=PRIORITY_SURVIVAL_FUND,
                    available_amount=survival,
                    fee_rate=0.0,
                    interest_rate=None,
                    coverage_impact="不影响保障",
                    notes="无手续费，不影响保障，优先推荐",
                ))

            # ---------- 红利领取 ----------
            bonus = float(pol.get("bounusAmt", 0) or 0)
            if bonus > 0:
                candidates.append(self._make_plan(
                    policy_id=policy_id,
                    product_name=product_name,
                    plan_type="bonus",
                    plan_name="红利领取",
                    priority=PRIORITY_BONUS,
                    available_amount=bonus,
                    fee_rate=0.0,
                    interest_rate=None,
                    coverage_impact="不影响保障",
                    notes="无手续费，不影响保障",
                ))

            # ---------- 部分领取 / 退保（按产品类型区分优先级）----------
            refund = float(pol.get("policyRefundAmount", 0) or 0)
            if refund > 0:
                fee_rate = _get_fee_rate(policy_year)
                if product_type == "universal_life":
                    # 万能险 → P2
                    candidates.append(self._make_plan(
                        policy_id=policy_id,
                        product_name=product_name,
                        plan_type="partial_withdrawal",
                        plan_name="万能险部分领取",
                        priority=PRIORITY_UNIVERSAL_LIFE,
                        available_amount=refund,
                        fee_rate=fee_rate,
                        interest_rate=None,
                        coverage_impact="现金价值减少，保额同步下降",
                        notes=f"第{policy_year}保单年度，手续费率{fee_rate:.0%}",
                        policy_year=policy_year,
                    ))
                elif product_type == "whole_life":
                    # 终身寿险 → P3（退保），退保无手续费
                    candidates.append(self._make_plan(
                        policy_id=policy_id,
                        product_name=product_name,
                        plan_type="surrender",
                        plan_name="退保",
                        priority=PRIORITY_WHOLE_LIFE,
                        available_amount=refund,
                        fee_rate=0.0,
                        interest_rate=None,
                        coverage_impact="所有保障终止",
                        notes="退保后保障失效，请谨慎考虑。无手续费，但保障完全终止",
                        policy_year=policy_year,
                    ))
                else:
                    # 其他类型（年金险等）→ P2
                    candidates.append(self._make_plan(
                        policy_id=policy_id,
                        product_name=product_name,
                        plan_type="partial_withdrawal",
                        plan_name="部分领取",
                        priority=PRIORITY_UNIVERSAL_LIFE,
                        available_amount=refund,
                        fee_rate=fee_rate,
                        interest_rate=None,
                        coverage_impact="账户价值减少",
                        notes=f"第{policy_year}保单年度，手续费率{fee_rate:.0%}",
                        policy_year=policy_year,
                    ))

            # ---------- 保单贷款 ----------
            loan = float(pol.get("loanAmt", 0) or 0)
            if loan > 0:
                candidates.append(self._make_plan(
                    policy_id=policy_id,
                    product_name=product_name,
                    plan_type="policy_loan",
                    plan_name="保单贷款",
                    priority=PRIORITY_POLICY_LOAN,
                    available_amount=loan,
                    fee_rate=0.0,
                    interest_rate=LOAN_INTEREST_RATE,
                    coverage_impact="不影响保障（未按时还款可能导致保单中止）",
                    notes=f"年利率{LOAN_INTEREST_RATE:.0%}，适合紧急周转且不想丧失保障的客户",
                ))

        # 排序：优先级 ASC → 净额 DESC
        candidates.sort(key=lambda c: (c["priority"], -c["net_amount"]))

        # 添加排名
        for i, c in enumerate(candidates, 1):
            c["rank"] = i
            c["priority_label"] = PRIORITY_LABELS.get(c["priority"], "")

        # 汇总
        total_available = sum(c["available_amount"] for c in candidates if c["plan_type"] != "policy_loan")
        total_with_loan = sum(c["available_amount"] for c in candidates)

        # 组合方案提示
        combination_hint = None
        if amount and amount > 0:
            # 检查是否有单个方案能满足
            single_ok = any(c["net_amount"] >= amount for c in candidates)
            if not single_ok and total_with_loan >= amount:
                combination_hint = (
                    f"单个方案无法满足 {amount:,.0f} 元的需求，"
                    f"建议组合多个方案（总可用约 {total_with_loan:,.0f} 元）。"
                )
            elif not single_ok:
                combination_hint = (
                    f"所有方案合计约 {total_with_loan:,.0f} 元，"
                    f"仍不足 {amount:,.0f} 元，请考虑调整金额。"
                )

        return {
            "requested_amount": amount,
            "total_available_excl_loan": total_available,
            "total_available_incl_loan": total_with_loan,
            "combination_hint": combination_hint,
            "plans": candidates,
        }

    # ------------------------------------------------------------------
    # calculate_detail: 单保单 + 单方案详细计算
    # ------------------------------------------------------------------

    def _calculate_detail(
        self,
        policy: dict[str, Any],
        plan_type: str,
        amount: float | None,
    ) -> dict[str, Any]:
        """对单张保单的某种方案做详细费用计算。"""
        policy_id = policy.get("policy_id", "")
        product_name = policy.get("product_name", "")
        effective_date = policy.get("effective_date", "")
        policy_year = _compute_policy_year(effective_date) if effective_date else 6

        field_map = {
            "survival_fund": ("survivalFundAmt", "生存金领取"),
            "bonus": ("bounusAmt", "红利领取"),
            "partial_withdrawal": ("policyRefundAmount", "部分领取"),
            "surrender": ("policyRefundAmount", "退保"),
            "policy_loan": ("loanAmt", "保单贷款"),
        }

        if plan_type not in field_map:
            return {"success": False, "error": f"不支持的方案类型: {plan_type}"}

        field_name, plan_name = field_map[plan_type]
        max_available = float(policy.get(field_name, 0) or 0)

        if max_available <= 0:
            return {
                "success": False,
                "error": f"该保单 {policy_id} 无可用的{plan_name}额度",
            }

        actual_amount = min(amount, max_available) if amount else max_available

        # 费用计算：退保无手续费，仅部分领取按保单年度收费
        if plan_type == "partial_withdrawal":
            fee_rate = _get_fee_rate(policy_year)
        else:
            # survival_fund, bonus, surrender, policy_loan 均无手续费
            fee_rate = 0.0

        fee = actual_amount * fee_rate
        net_amount = actual_amount - fee

        result: dict[str, Any] = {
            "success": True,
            "policy_id": policy_id,
            "product_name": product_name,
            "plan_type": plan_type,
            "plan_name": plan_name,
            "max_available": max_available,
            "requested_amount": amount,
            "actual_amount": actual_amount,
            "fee_rate": fee_rate,
            "fee": round(fee, 2),
            "net_amount": round(net_amount, 2),
            "processing_time": PROCESSING_TIME,
            "policy_year": policy_year,
        }

        # 方案特有信息
        if plan_type == "policy_loan":
            result["interest_rate"] = LOAN_INTEREST_RATE
            result["interest_annual"] = round(actual_amount * LOAN_INTEREST_RATE, 2)
            result["interest_monthly"] = round(actual_amount * LOAN_INTEREST_RATE / 12, 2)
            result["coverage_impact"] = "不影响保障（未按时还款可能导致保单中止）"
        elif plan_type == "surrender":
            result["coverage_impact"] = "所有保障终止，退保后无法恢复"
        elif plan_type == "partial_withdrawal":
            result["coverage_impact"] = "现金价值减少，保额同步下降"
        else:
            result["coverage_impact"] = "不影响保障"

        if amount and amount > max_available:
            result["warning"] = f"请求金额 {amount:,.0f} 元超过可用额度 {max_available:,.0f} 元，已按最大额度计算"

        return result

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------

    @staticmethod
    def _make_plan(
        *,
        policy_id: str,
        product_name: str,
        plan_type: str,
        plan_name: str,
        priority: int,
        available_amount: float,
        fee_rate: float,
        interest_rate: float | None,
        coverage_impact: str,
        notes: str,
        policy_year: int | None = None,
    ) -> dict[str, Any]:
        """构造一个候选方案字典。"""
        fee = round(available_amount * fee_rate, 2)
        net_amount = round(available_amount - fee, 2)

        plan: dict[str, Any] = {
            "policy_id": policy_id,
            "product_name": product_name,
            "plan_type": plan_type,
            "plan_name": plan_name,
            "priority": priority,
            "available_amount": available_amount,
            "fee_rate": fee_rate,
            "fee": fee,
            "net_amount": net_amount,
            "processing_time": PROCESSING_TIME,
            "coverage_impact": coverage_impact,
            "notes": notes,
        }

        if interest_rate is not None:
            plan["interest_rate"] = interest_rate
            plan["interest_annual"] = round(available_amount * interest_rate, 2)

        if policy_year is not None:
            plan["policy_year"] = policy_year

        return plan
