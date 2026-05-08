"""
规则引擎工具

查询用户保单数据，标准化为每张保单一条记录，包含四个可用金额字段和费率信息。
基于保单数据中的四个金额字段进行确定性计算：
  - bonusAmt           红利
  - loanAmt             可贷款额度
  - survivalFundAmt     生存金 / 满期金
  - policyRefundAmount  退保金额（部分领取 / 全额退保）

list_options 通过 user_id 自行获取保单数据，无需 LLM 中转。
返回每张保单一条记录（含四个金额字段），由 LLM 根据用户需求从中组装最终推荐方案。
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
import json

from ark_agentic.core.types import AgentToolResult, ToolCall

from ..a2ui.withdraw_a2ui_utils import _channel_available
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

    list_options: 接收 user_id，获取保单数据，返回每张保单的标准化信息（含四个金额字段）。
    calculate_detail: 接收单张保单数据和取款渠道类型，做精确费用计算。
    """

    name = "rule_engine"
    description = (
        "查询保单数据并返回标准化的保单信息。"
        "list_options 根据 user_id 自动获取保单数据，返回每张保单的四个可用金额和费率；"
        "calculate_detail 对单张保单的某个取款渠道做详细费用计算。"
    )
    thinking_hint = "正在计算取款方案…"
    group = "insurance"
    data_source = True

    parameters = [
        ToolParameter(
            name="action",
            type="string",
            description="操作类型：list_options（列出保单可用金额）或 calculate_detail（单渠道详算）",
            required=True,
            enum=["list_options", "calculate_detail"],
        ),
        ToolParameter(
            name="user_id",
            type="string",
            description="用户ID（list_options 时必填），规则引擎会自动查询该用户的保单数据",
            required=False,
        ),
        ToolParameter(
            name="policy",
            type="object",
            description="单张保单数据（calculate_detail 时必填），从 list_options 返回的保单对象",
            required=False,
        ),
        ToolParameter(
            name="option_type",
            type="string",
            description="取款渠道类型（calculate_detail 时必填）",
            required=False,
            enum=["survival_fund", "bonus", "partial_withdrawal", "surrender", "policy_loan"],
        ),
        ToolParameter(
            name="amount",
            type="number",
            description="期望金额（可选，不提供则返回各渠道最大可用额度）",
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

        if action == "list_options":
            user_id = read_string_param(args, "user_id")
            if not user_id:
                return AgentToolResult.error_result(
                    tool_call.id, "list_options 需要提供 user_id 参数"
                )
            amount = read_float_param(args, "amount")
            try:
                result = await self._list_options(user_id, amount)
            except DataServiceError as exc:
                logger.error(f"rule_engine list_options data fetch error: {exc}")
                return AgentToolResult.error_result(tool_call.id, f"获取保单数据失败: {exc}")

        elif action == "calculate_detail":
            policy = read_dict_param(args, "policy")
            if not policy:
                return AgentToolResult.error_result(
                    tool_call.id, "calculate_detail 需要提供 policy 参数（单张保单数据）"
                )
            option_type = read_string_param(args, "option_type")
            if not option_type:
                return AgentToolResult.error_result(
                    tool_call.id, "calculate_detail 需要提供 option_type 参数"
                )
            amount = read_float_param(args, "amount")
            result = self._calculate_detail(policy, option_type, amount)

        else:
            return AgentToolResult.error_result(
                tool_call.id, f"不支持的操作: {action}"
            )

        metadata: dict[str, Any] = {}
        llm_digest: str | None = None
        if action == "list_options":
            metadata["state_delta"] = {"_rule_engine_result": result}
            llm_summary = self._build_llm_summary(result)
            llm_digest = json.dumps(llm_summary, ensure_ascii=False)

        return AgentToolResult.json_result(
            tool_call.id, result, metadata=metadata or None, llm_digest=llm_digest,
        )

    # ------------------------------------------------------------------
    # list_options: 自动获取保单数据 → 标准化为每张保单一条记录
    # ------------------------------------------------------------------

    async def _list_options(
        self,
        user_id: str,
        amount: float | None,
    ) -> dict[str, Any]:
        """通过 user_id 获取保单列表，标准化为每张保单一条记录。"""
        data = await self._client.call(
            api_code=DataServiceClient.API_POLICY_QUERY,
            user_id=user_id,
            query_type="list",
        )
        policies = data.get("policyAssertList", [])
        if not policies:
            return {
                "requested_amount": amount,
                "total_available_excl_loan": 0,
                "total_available_incl_loan": 0,
                "combination_hint": "未找到该用户的有效保单",
                "options": [],
            }

        out = self._build_options(policies, amount)
        return out

    def _build_options(
        self,
        policies: list[dict[str, Any]],
        amount: float | None,
    ) -> dict[str, Any]:
        """遍历所有保单，每张保单产出一条标准化记录（含四个金额字段和费率）。"""
        options: list[dict[str, Any]] = []

        for pol in policies:
            effective_date = pol.get("effective_date", "")
            policy_year = _compute_policy_year(effective_date) if effective_date else 6

            survival = float(pol.get("survivalFundAmt", 0) or 0)
            bonus = float(pol.get("bonusAmt", 0) or 0)
            loan = float(pol.get("loanAmt", 0) or 0)
            refund = float(pol.get("policyRefundAmount", 0) or 0)
            total = survival + bonus + loan + refund

            if total <= 0:
                continue

            options.append({
                "policy_id": pol.get("policy_id", ""),
                "product_name": pol.get("product_name", ""),
                "product_type": pol.get("product_type", ""),
                "policy_year": policy_year,
                "available_amount": total,
                "survival_fund_amt": survival,
                "bonus_amt": bonus,
                "loan_amt": loan,
                "refund_amt": refund,
                "refund_fee_rate": _get_fee_rate(policy_year),
                "loan_interest_rate": LOAN_INTEREST_RATE if loan > 0 else None,
                "processing_time": PROCESSING_TIME,
            })

        # 按 available_amount 降序排列
        options.sort(key=lambda o: -o["available_amount"])

        # 汇总
        total_excl_loan = sum(
            o["survival_fund_amt"] + o["bonus_amt"] + o["refund_amt"]
            for o in options
        )
        total_incl_loan = sum(o["available_amount"] for o in options)

        # 组合提示
        combination_hint = None
        if amount and amount > 0:
            # 检查是否有单张保单的总额能满足
            single_ok = any(o["available_amount"] >= amount for o in options)
            if not single_ok and total_incl_loan >= amount:
                combination_hint = (
                    f"单张保单无法满足 {amount:,.0f} 元的需求，"
                    f"需组合多张保单（总可用约 {total_incl_loan:,.0f} 元）。"
                )
            elif not single_ok:
                combination_hint = (
                    f"所有保单合计约 {total_incl_loan:,.0f} 元，"
                    f"仍不足 {amount:,.0f} 元，请考虑调整金额。"
                )

        return {
            "requested_amount": amount,
            "total_available_excl_loan": total_excl_loan,
            "total_available_incl_loan": total_incl_loan,
            "combination_hint": combination_hint,
            "options": options,
        }

    # ------------------------------------------------------------------
    # LLM-visible summary (渠道级汇总，隐藏保单级明细)
    # ------------------------------------------------------------------

    @staticmethod
    def _build_channel_summary(options: list[dict[str, Any]]) -> dict[str, Any]:
        sf = sum(_channel_available(o, "survival_fund") for o in options)
        bon = sum(_channel_available(o, "bonus") for o in options)
        pw = sum(_channel_available(o, "partial_withdrawal") for o in options)
        loan = sum(_channel_available(o, "policy_loan") for o in options)
        surr = sum(_channel_available(o, "surrender") for o in options)
        return {
            "zero_cost": {"total": sf + bon, "note": "不影响保障"},
            "survival_fund": {"total": sf},
            "bonus": {"total": bon},
            "partial_withdrawal": {"total": pw, "note": "保额降低，可能有手续费"},
            "policy_loan": {"total": loan, "note": "年利率5%，保障不受影响"},
            "surrender": {"total": surr, "note": "保障终止"},
        }

    @staticmethod
    def _build_llm_summary(result: dict[str, Any]) -> dict[str, Any]:
        options = result.get("options", [])
        return {
            "status": "ok",
            "policy_count": len(options),
            "channels": RuleEngineTool._build_channel_summary(options),
            "grand_total": result.get("total_available_incl_loan", 0),
            "combination_hint": result.get("combination_hint"),
        }

    # ------------------------------------------------------------------
    # calculate_detail: 单保单 + 单渠道详细计算
    # ------------------------------------------------------------------

    def _calculate_detail(
        self,
        policy: dict[str, Any],
        option_type: str,
        amount: float | None,
    ) -> dict[str, Any]:
        """对单张保单的某个取款渠道做详细费用计算。

        policy 参数可以是 list_options 返回的标准化对象，
        也可以是原始保单数据（两种字段名都支持）。
        """
        policy_id = policy.get("policy_id", "")
        product_name = policy.get("product_name", "")
        policy_year = policy.get("policy_year")
        if policy_year is None:
            effective_date = policy.get("effective_date", "")
            policy_year = _compute_policy_year(effective_date) if effective_date else 6

        # 支持标准化字段名和原始字段名
        field_map = {
            "survival_fund": (
                ["survival_fund_amt", "survivalFundAmt"],
                "生存金领取",
            ),
            "bonus": (
                ["bonus_amt", "bonusAmt"],
                "红利领取",
            ),
            "partial_withdrawal": (
                ["refund_amt", "policyRefundAmount"],
                "部分领取",
            ),
            "surrender": (
                ["refund_amt", "policyRefundAmount"],
                "退保",
            ),
            "policy_loan": (
                ["loan_amt", "loanAmt"],
                "保单贷款",
            ),
        }

        if option_type not in field_map:
            return {"success": False, "error": f"不支持的渠道类型: {option_type}"}

        field_names, option_name = field_map[option_type]

        # 尝试多个字段名
        max_available = 0.0
        for fn in field_names:
            val = policy.get(fn)
            if val is not None:
                max_available = float(val or 0)
                if max_available > 0:
                    break

        if max_available <= 0:
            return {
                "success": False,
                "error": f"该保单 {policy_id} 无可用的{option_name}额度",
            }

        actual_amount = min(amount, max_available) if amount else max_available

        # 费用计算：退保无手续费，仅部分领取按保单年度收费
        if option_type == "partial_withdrawal":
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
            "option_type": option_type,
            "option_name": option_name,
            "max_available": max_available,
            "requested_amount": amount,
            "actual_amount": actual_amount,
            "fee_rate": fee_rate,
            "fee": round(fee, 2),
            "net_amount": round(net_amount, 2),
            "processing_time": PROCESSING_TIME,
            "policy_year": policy_year,
        }

        # 渠道特有信息
        if option_type == "policy_loan":
            result["interest_rate"] = LOAN_INTEREST_RATE
            result["interest_annual"] = round(actual_amount * LOAN_INTEREST_RATE, 2)
            result["interest_monthly"] = round(actual_amount * LOAN_INTEREST_RATE / 12, 2)
            result["coverage_impact"] = "不影响保障（未按时还款可能导致保单中止）"
        elif option_type == "surrender":
            result["coverage_impact"] = "所有保障终止，退保后无法恢复"
        elif option_type == "partial_withdrawal":
            result["coverage_impact"] = "现金价值减少，保额同步下降"
        else:
            result["coverage_impact"] = "不影响保障"

        if amount and amount > max_available:
            result["warning"] = f"请求金额 {amount:,.0f} 元超过可用额度 {max_available:,.0f} 元，已按最大额度计算"

        return result
