"""WithdrawalFlowEvaluator — 保险取款 4 阶段流程评估器。

阶段:
  1. identity_verify — 身份核验（customer_info, policy_query）
  2. options_query   — 方案查询（rule_engine）
  3. plan_confirm    — 方案确认，wait_for_user=True（render_a2ui）
  4. execute         — 执行取款（submit_withdrawal）

业务工具通过 state_delta 点路径写入阶段数据：
  metadata={"state_delta": {"_flow_context.stage_identity_verify": {...}}}

工具名: "withdraw_money_flow_evaluator"（注册到 required_tools 时使用此名）
"""

from __future__ import annotations

from pydantic import BaseModel

from ark_agentic.core.flow.base_evaluator import BaseFlowEvaluator, FlowEvaluatorRegistry, StageDefinition


# ── 各阶段 Pydantic 完成条件 Schema ─────────────────────────────────────────


class IdentityVerifyOutput(BaseModel):
    """身份核验阶段完成条件"""
    user_id: str
    id_card_verified: bool
    policy_ids: list[str]


class OptionsQueryOutput(BaseModel):
    """方案查询阶段完成条件"""
    available_options: list[dict]
    total_cash_value: float
    max_withdrawal: float


class PlanConfirmOutput(BaseModel):
    """方案确认阶段完成条件（用户确认后写入）"""
    confirmed: bool
    selected_option: dict
    amount: float


class ExecuteOutput(BaseModel):
    """执行阶段完成条件"""
    transaction_id: str
    status: str  # "submitted" | "pending" | "failed"


# ── WithdrawalFlowEvaluator ──────────────────────────────────────────────────


class WithdrawalFlowEvaluator(BaseFlowEvaluator):
    """保险取款 4 阶段流程评估器（业务层实现）。

    继承 BaseFlowEvaluator，仅定义阶段列表和 Pydantic schema。
    """

    @property
    def skill_name(self) -> str:
        return "withdraw_money_flow"

    @property
    def stages(self) -> list[StageDefinition]:
        return [
            StageDefinition(
                id="identity_verify",
                name="身份核验",
                description="验证客户身份和保单信息",
                required=True,
                output_schema=IdentityVerifyOutput,
                reference_file="identity_verify.md",
                tools=["customer_info", "policy_query"],
            ),
            StageDefinition(
                id="options_query",
                name="方案查询",
                description="查询可取款选项和金额",
                required=True,
                output_schema=OptionsQueryOutput,
                reference_file="options_query.md",
                tools=["rule_engine"],
            ),
            StageDefinition(
                id="plan_confirm",
                name="方案确认",
                description="向用户展示方案并等待确认",
                required=True,
                wait_for_user=True,
                output_schema=PlanConfirmOutput,
                reference_file="plan_confirm.md",
                tools=["render_a2ui"],
            ),
            StageDefinition(
                id="execute",
                name="执行取款",
                description="提交取款操作",
                required=True,
                output_schema=ExecuteOutput,
                reference_file="execute.md",
                tools=["submit_withdrawal"],
            ),
        ]


# 全局单例，随模块 import 自动注册
withdrawal_flow_evaluator = WithdrawalFlowEvaluator()
FlowEvaluatorRegistry.register(withdrawal_flow_evaluator)
